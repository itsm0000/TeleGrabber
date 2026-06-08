import asyncio
from app.db.supabase import get_supabase

def test_results():
    supabase = get_supabase()
    job_id = "f166e75f-88fd-4ff3-ab4d-0ca0edbd24e3"
    
    print("Testing extraction_jobs select")
    try:
        job_resp = supabase.table("extraction_jobs").select("message_count").eq("id", job_id).maybe_single().execute()
        print("job_resp:", job_resp)
    except Exception as e:
        print("Error in job_resp:", e)

    print("Testing messages select")
    try:
        rows_resp = (
            supabase.table("messages")
            .select("*")
            .eq("job_id", job_id)
            .order("date", desc=False)
            .range(0, 99)
            .execute()
        )
        print("rows_resp length:", len(rows_resp.data))
        if len(rows_resp.data) > 0:
            print("First row:", rows_resp.data[0])
    except Exception as e:
        print("Error in rows_resp:", e)

if __name__ == "__main__":
    test_results()
