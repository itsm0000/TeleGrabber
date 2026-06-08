from app.db.supabase import get_supabase
from app.models.schemas import ExtractedMessageOut
from pydantic import ValidationError

supabase = get_supabase()
job_id = 'f166e75f-88ff-4f8c-b6c9-c67a9a8d5209'
rows_resp = supabase.table('messages').select('*').eq('job_id', job_id).order('date', desc=False).range(0, 99).execute()

for i, row in enumerate(rows_resp.data):
    try:
        ExtractedMessageOut(**row)
    except ValidationError as e:
        print(f"Row {i} failed validation:")
        print(row)
        print(e)
        break
else:
    print("All rows validated successfully!")
