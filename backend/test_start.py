import asyncio
from uuid import UUID
from app.db.supabase import get_supabase

def test_insert():
    supabase = get_supabase()
    job_data = {
        "phone": "+9647731706454",
        "source_url": "https://t.me/c/2400482838/3800",
        "entity_ref": "2400482838",
        "topic_id": None,
        "link_type": "private_chat",
        "status": "pending",
        "max_messages": None,
        "filters_json": None,
    }
    try:
        job_row = supabase.table("extraction_jobs").insert(job_data).execute()
        print("Success:", job_row.data)
    except Exception as e:
        print("Error:", e)

if __name__ == "__main__":
    test_insert()
