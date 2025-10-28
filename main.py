import os
from datetime import datetime, timezone
from typing import List, Optional, Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from bson import ObjectId

from database import db, create_document, get_documents

app = FastAPI(title="Accounting CRM API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- Models ----------
class Comment(BaseModel):
    role: Literal["creator", "reviewer", "approver"]
    message: str
    at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AccountingEntry(BaseModel):
    title: str
    amount: float
    description: Optional[str] = None
    status: Literal[
        "draft",
        "submitted_for_review",
        "reentry_requested",
        "recheck_requested",
        "reviewed",
        "approved",
    ] = "draft"
    comments: List[Comment] = Field(default_factory=list)
    frozen: bool = False


# ---------- Helpers ----------

def obj_id(id_str: str) -> ObjectId:
    try:
        return ObjectId(id_str)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid entry id")


def serialize(doc: dict):
    if not doc:
        return None
    d = doc.copy()
    d["id"] = str(d.pop("_id"))
    # Convert datetime to isoformat for JSON
    for c in d.get("comments", []) or []:
        if isinstance(c.get("at"), datetime):
            c["at"] = c["at"].isoformat()
    if isinstance(d.get("created_at"), datetime):
        d["created_at"] = d["created_at"].isoformat()
    if isinstance(d.get("updated_at"), datetime):
        d["updated_at"] = d["updated_at"].isoformat()
    return d


# ---------- Basic Routes ----------
@app.get("/")
def read_root():
    return {"message": "Accounting CRM Backend is running"}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": [],
    }
    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
            response["database_name"] = db.name if hasattr(db, "name") else "✅ Connected"
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️ Connected but Error: {str(e)[:80]}"
        else:
            response["database"] = "⚠️ Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:80]}"
    return response


# ---------- Accounting Entry Endpoints ----------

@app.get("/api/entries")
def list_entries(status: Optional[str] = None):
    filt = {}
    if status:
        filt["status"] = status
    docs = get_documents("accountingentry", filt)
    return [serialize(d) for d in docs]


@app.post("/api/entries")
def create_entry(entry: AccountingEntry):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    inserted_id = create_document("accountingentry", entry)
    doc = db["accountingentry"].find_one({"_id": ObjectId(inserted_id)})
    return serialize(doc)


class UpdateEntryPayload(BaseModel):
    title: Optional[str] = None
    amount: Optional[float] = None
    description: Optional[str] = None
    role: Literal["creator", "reviewer", "approver", "blackadam"]


@app.patch("/api/entries/{entry_id}")
def update_entry(entry_id: str, payload: UpdateEntryPayload):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    doc = db["accountingentry"].find_one({"_id": obj_id(entry_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Entry not found")

    if doc.get("frozen"):
        raise HTTPException(status_code=400, detail="Entry is frozen and cannot be updated")

    if doc.get("status") not in ["draft", "reentry_requested"]:
        raise HTTPException(status_code=400, detail="Entry can only be updated in draft or reentry_requested state")

    updates = {}
    if payload.title is not None:
        updates["title"] = payload.title
    if payload.amount is not None:
        updates["amount"] = payload.amount
    if payload.description is not None:
        updates["description"] = payload.description
    if not updates:
        return serialize(doc)

    updates["updated_at"] = datetime.now(timezone.utc)
    db["accountingentry"].update_one({"_id": obj_id(entry_id)}, {"$set": updates})
    new_doc = db["accountingentry"].find_one({"_id": obj_id(entry_id)})
    return serialize(new_doc)


class RolePayload(BaseModel):
    role: Literal["creator", "reviewer", "approver", "blackadam"]
    comment: Optional[str] = None


@app.patch("/api/entries/{entry_id}/submit")
def submit_for_review(entry_id: str, payload: RolePayload):
    doc = db["accountingentry"].find_one({"_id": obj_id(entry_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Entry not found")
    if doc.get("frozen"):
        raise HTTPException(status_code=400, detail="Entry is frozen")
    if payload.role not in ["creator", "blackadam"]:
        raise HTTPException(status_code=403, detail="Only creator can submit for review")
    if doc.get("status") not in ["draft", "reentry_requested"]:
        raise HTTPException(status_code=400, detail="Only draft or reentry_requested entries can be submitted")

    updates = {
        "status": "submitted_for_review",
        "updated_at": datetime.now(timezone.utc),
    }
    if payload.comment:
        comment = Comment(role="creator", message=payload.comment).model_dump()
        db["accountingentry"].update_one({"_id": obj_id(entry_id)}, {"$push": {"comments": comment}})
    db["accountingentry"].update_one({"_id": obj_id(entry_id)}, {"$set": updates})
    return serialize(db["accountingentry"].find_one({"_id": obj_id(entry_id)}))


class ReviewerActionPayload(BaseModel):
    role: Literal["reviewer", "blackadam"]
    action: Literal["mark_reviewed", "request_reentry"]
    comment: Optional[str] = None


@app.patch("/api/entries/{entry_id}/review")
def reviewer_action(entry_id: str, payload: ReviewerActionPayload):
    doc = db["accountingentry"].find_one({"_id": obj_id(entry_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Entry not found")
    if doc.get("frozen"):
        raise HTTPException(status_code=400, detail="Entry is frozen")
    if doc.get("status") not in ["submitted_for_review", "recheck_requested"]:
        raise HTTPException(status_code=400, detail="Entry is not ready for reviewer action")

    if payload.action == "mark_reviewed":
        updates = {"status": "reviewed"}
        comment_role = "reviewer"
        default_msg = "Marked as reviewed"
    else:
        updates = {"status": "reentry_requested"}
        comment_role = "reviewer"
        default_msg = "Re-entry requested"

    updates["updated_at"] = datetime.now(timezone.utc)

    if payload.comment or default_msg:
        message = payload.comment or default_msg
        comment = Comment(role=comment_role, message=message).model_dump()
        db["accountingentry"].update_one({"_id": obj_id(entry_id)}, {"$push": {"comments": comment}})

    db["accountingentry"].update_one({"_id": obj_id(entry_id)}, {"$set": updates})
    return serialize(db["accountingentry"].find_one({"_id": obj_id(entry_id)}))


class ApproverActionPayload(BaseModel):
    role: Literal["approver", "blackadam"]
    action: Literal["approve", "request_rereview"]
    comment: Optional[str] = None


@app.patch("/api/entries/{entry_id}/approve")
def approver_action(entry_id: str, payload: ApproverActionPayload):
    doc = db["accountingentry"].find_one({"_id": obj_id(entry_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Entry not found")
    if doc.get("frozen"):
        raise HTTPException(status_code=400, detail="Entry is frozen")
    if doc.get("status") != "reviewed":
        raise HTTPException(status_code=400, detail="Only reviewed entries can be approved or re-reviewed")

    if payload.action == "approve":
        updates = {"status": "approved", "frozen": True}
        default_msg = "Approved"
    else:
        updates = {"status": "recheck_requested"}
        default_msg = "Re-review requested"

    updates["updated_at"] = datetime.now(timezone.utc)

    message = payload.comment or default_msg
    comment = Comment(role="approver", message=message).model_dump()
    db["accountingentry"].update_one({"_id": obj_id(entry_id)}, {"$push": {"comments": comment}})

    db["accountingentry"].update_one({"_id": obj_id(entry_id)}, {"$set": updates})
    return serialize(db["accountingentry"].find_one({"_id": obj_id(entry_id)}))


@app.get("/api/entries/{entry_id}")
def get_entry(entry_id: str):
    doc = db["accountingentry"].find_one({"_id": obj_id(entry_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Entry not found")
    return serialize(doc)


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
