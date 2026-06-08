from app.db.supabase import get_supabase
from app.models.schemas import ExtractedMessageOut, JobResultsResponse
import uuid

supabase = get_supabase()
job_id = 'f166e75f-88ff-4f8c-b6c9-c67a9a8d5209'
rows_resp = supabase.table('messages').select('*').eq('job_id', job_id).order('date', desc=False).range(0, 99).execute()

messages = [ExtractedMessageOut(**row) for row in rows_resp.data]

try:
    resp = JobResultsResponse(job_id=uuid.UUID(job_id), total=332, messages=messages)
    print("JobResultsResponse instantiated successfully")
except Exception as e:
    print(e)
