"""
Recommendation service for reading from MongoDB and writing approval changes.
"""
import logging
from datetime import datetime
from typing import Optional, Dict, Any
from uuid import UUID
from bson import ObjectId

logger = logging.getLogger(__name__)


async def get_recommendation_result(mongo_db, result_id: str) -> dict:
    """
    Read a completed recommendation result from MongoDB.
    Strips internal fields (blocked_count, blocked_reasons, source_agent_runs).
    """
    try:
        doc = await mongo_db["recommendations"].find_one({"_id": ObjectId(result_id)})
        if not doc:
            raise ValueError(f"Recommendation result not found: {result_id}")

        # Strip internal fields
        doc.pop("blocked_count", None)
        doc.pop("blocked_reasons", None)
        doc.pop("source_agent_runs", None)

        # Convert _id to string
        doc["_id"] = str(doc["_id"])

        return doc
    except Exception as exc:
        logger.error(f"Failed to get recommendation result {result_id}: {exc}")
        raise


async def find_recommendation_by_id(mongo_db, client_id: str, recommendation_id: str) -> Optional[tuple]:
    """
    Find a recommendation item by ID within a client's documents.
    Returns (document, array_index) or (None, None) if not found.
    """
    # First, find which document contains this recommendation
    doc = await mongo_db["recommendations"].find_one({
        "client_id": client_id,
        "recommendations.id": recommendation_id
    })

    if not doc:
        return None, None

    # Find the index of the matching recommendation in the array
    for idx, rec in enumerate(doc.get("recommendations", [])):
        if rec.get("id") == recommendation_id:
            return doc, idx

    return None, None


async def approve_recommendation(
    mongo_db,
    client_id: str,
    recommendation_id: str,
    approved_by: str,
    notes: str,
) -> dict:
    """
    Update a recommendation's approval status to 'Approved'.

    Returns the updated recommendation item.
    Raises ValueError if the recommendation doesn't exist or is already actioned.
    """
    doc, idx = await find_recommendation_by_id(mongo_db, client_id, recommendation_id)

    if not doc:
        raise ValueError(f"Recommendation not found: {recommendation_id}")

    # Check if already actioned
    current_status = doc["recommendations"][idx].get("approval_status")
    if current_status in ["Approved", "Rejected", "Overridden"]:
        raise ValueError(f"Recommendation has already been actioned: {current_status}")

    # Update using MongoDB positional operator
    await mongo_db["recommendations"].update_one(
        {"client_id": client_id, "recommendations.id": recommendation_id},
        {"$set": {
            "recommendations.$.approval_status": "Approved",
            "recommendations.$.approved_by": approved_by,
            "recommendations.$.approved_at": datetime.utcnow(),
            "recommendations.$.notes": notes,
        }}
    )

    # Fetch and return updated item
    updated_doc = await mongo_db["recommendations"].find_one({
        "client_id": client_id,
        "recommendations.id": recommendation_id
    })

    if not updated_doc:
        raise ValueError(f"Failed to retrieve updated recommendation: {recommendation_id}")

    for rec in updated_doc.get("recommendations", []):
        if rec.get("id") == recommendation_id:
            return rec

    raise ValueError(f"Recommendation not found after update: {recommendation_id}")


async def reject_recommendation(
    mongo_db,
    client_id: str,
    recommendation_id: str,
    rejected_by: str,
    reason: str,
) -> dict:
    """
    Update a recommendation's approval status to 'Rejected'.

    Returns the updated recommendation item.
    Raises ValueError if the recommendation doesn't exist or is already actioned.
    """
    doc, idx = await find_recommendation_by_id(mongo_db, client_id, recommendation_id)

    if not doc:
        raise ValueError(f"Recommendation not found: {recommendation_id}")

    # Check if already actioned
    current_status = doc["recommendations"][idx].get("approval_status")
    if current_status in ["Approved", "Rejected", "Overridden"]:
        raise ValueError(f"Recommendation has already been actioned: {current_status}")

    # Update using MongoDB positional operator
    await mongo_db["recommendations"].update_one(
        {"client_id": client_id, "recommendations.id": recommendation_id},
        {"$set": {
            "recommendations.$.approval_status": "Rejected",
            "recommendations.$.rejected_by": rejected_by,
            "recommendations.$.rejected_at": datetime.utcnow(),
            "recommendations.$.rejection_reason": reason,
        }}
    )

    # Fetch and return updated item
    updated_doc = await mongo_db["recommendations"].find_one({
        "client_id": client_id,
        "recommendations.id": recommendation_id
    })

    if not updated_doc:
        raise ValueError(f"Failed to retrieve updated recommendation: {recommendation_id}")

    for rec in updated_doc.get("recommendations", []):
        if rec.get("id") == recommendation_id:
            return rec

    raise ValueError(f"Recommendation not found after update: {recommendation_id}")


async def override_recommendation(
    mongo_db,
    client_id: str,
    recommendation_id: str,
    overridden_by: str,
    action_taken: str,
    notes: str,
) -> dict:
    """
    Update a recommendation's approval status to 'Overridden'.

    Returns the updated recommendation item.
    Raises ValueError if the recommendation doesn't exist or is already actioned.
    """
    doc, idx = await find_recommendation_by_id(mongo_db, client_id, recommendation_id)

    if not doc:
        raise ValueError(f"Recommendation not found: {recommendation_id}")

    # Check if already actioned
    current_status = doc["recommendations"][idx].get("approval_status")
    if current_status in ["Approved", "Rejected", "Overridden"]:
        raise ValueError(f"Recommendation has already been actioned: {current_status}")

    # Update using MongoDB positional operator
    await mongo_db["recommendations"].update_one(
        {"client_id": client_id, "recommendations.id": recommendation_id},
        {"$set": {
            "recommendations.$.approval_status": "Overridden",
            "recommendations.$.overridden_by": overridden_by,
            "recommendations.$.overridden_at": datetime.utcnow(),
            "recommendations.$.action_taken": action_taken,
            "recommendations.$.notes": notes,
        }}
    )

    # Fetch and return updated item
    updated_doc = await mongo_db["recommendations"].find_one({
        "client_id": client_id,
        "recommendations.id": recommendation_id
    })

    if not updated_doc:
        raise ValueError(f"Failed to retrieve updated recommendation: {recommendation_id}")

    for rec in updated_doc.get("recommendations", []):
        if rec.get("id") == recommendation_id:
            return rec

    raise ValueError(f"Recommendation not found after update: {recommendation_id}")


async def get_pending_approvals_count(mongo_db, request_id: str) -> int:
    """
    Count the number of recommendations with approval_status = "Pending" for a given request_id.
    """
    doc = await mongo_db["recommendations"].find_one({"_id": ObjectId(request_id)})
    if not doc:
        return 0

    count = sum(1 for rec in doc.get("recommendations", []) if rec.get("approval_status") == "Pending")
    return count
