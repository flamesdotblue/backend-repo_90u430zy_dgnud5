"""
Database Schemas

Define your MongoDB collection schemas here using Pydantic models.
Each Pydantic model represents a collection in your database.
Model name is converted to lowercase for the collection name:
- User -> "user" collection
- Product -> "product" collection
- AccountingEntry -> "accountingentry" collection
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Literal
from datetime import datetime, timezone

# Example schemas (you can keep or remove these if not needed in your app)
class User(BaseModel):
    name: str = Field(..., description="Full name")
    email: str = Field(..., description="Email address")
    address: str = Field(..., description="Address")
    age: Optional[int] = Field(None, ge=0, le=120, description="Age in years")
    is_active: bool = Field(True, description="Whether user is active")


class Product(BaseModel):
    title: str = Field(..., description="Product title")
    description: Optional[str] = Field(None, description="Product description")
    price: float = Field(..., ge=0, description="Price in dollars")
    category: str = Field(..., description="Product category")
    in_stock: bool = Field(True, description="Whether product is in stock")


# Accounting CRM Schemas
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
