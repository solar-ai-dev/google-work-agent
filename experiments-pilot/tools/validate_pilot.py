import json, sys, re
from pathlib import Path
BASE=Path(__file__).resolve().parents[1]

def load(rel):
    return [json.loads(x) for x in (BASE/rel).read_text(encoding='utf-8').splitlines() if x.strip()]

cases=load('datasets/cases/pilot.jsonl')
resources=[]
for f in ['gmail-resources.jsonl','task-resources.jsonl','calendar-resources.jsonl']:
    resources += load('datasets/google_workspace/corpus/'+f)
segments=load('datasets/google_workspace/segments/source-segments.jsonl')
classify=load('datasets/agent_prompt/request_understanding/classify.jsonl')
plans=load('datasets/agent_prompt/api_discovery_acquisition/plan_sources.jsonl')
ctx=load('datasets/agent_prompt/context_retriever/select_evidence.jsonl')
drafts=load('datasets/agent_prompt/solution_planning/draft_plan.jsonl')
reviews=load('datasets/agent_prompt/plan_review/inspect.jsonl')
errors=[]
if len(cases)!=5: errors.append(f'cases={len(cases)}')
allowed_tools={'gmail_create_draft','gmail_update_draft','tasks_create_task','tasks_update_task','calendar_create_event','calendar_update_event'}
for r in resources:
    text=r['body_or_description'].lower()
    for bad in ['정답 근거','hard negative','required resource','승인이 나면 검증','이번 요청의 직접 산출물']:
        if bad in text: errors.append(f'evaluation label in resource {r["resource_id"]}: {bad}')
for row in classify:
    if row['gold']['result'] not in {'COMPLETE','NEEDS_CONFIRMATION','INVALID'}: errors.append('bad classify result '+row['case_id'])
for row in plans:
    if row['gold']['result'] not in {'PLAN_READY','NO_FETCH_NEEDED','NEEDS_CONFIRMATION','BLOCKED'}: errors.append('bad plan_sources result '+row['case_id'])
for row in ctx:
    if row['gold']['result'] not in {'SELECTED','PARTIAL','BLOCKED'}: errors.append('bad context result '+row['case_id'])
for row in drafts:
    if row['gold']['result'] not in {'PLAN_READY','NEEDS_CONFIRMATION','BLOCKED'}: errors.append('bad draft result '+row['case_id'])
    for a in row['gold']['action_dag']:
        if a['tool_name'] not in allowed_tools: errors.append('bad tool '+a['tool_name'])
        if a['effect_type']=='CREATE' and a.get('target_resource_id') is not None: errors.append('CREATE target resource '+a['action_id'])
        if a['effect_type']=='UPDATE' and not a.get('target_resource_id'): errors.append('UPDATE missing target '+a['action_id'])
if not any(c['expected_route']=='READ_ONLY' for c in cases): errors.append('no READ_ONLY case')
if set(r['gold']['decision'] for r in reviews) != {'PASS','REVISE','CONFIRM','BLOCK'}: errors.append('review decision diversity missing')
if errors:
    print('FAIL')
    for e in errors: print('-',e)
    sys.exit(1)
print('PASS')
print('cases',len(cases),'resources',len(resources),'segments',len(segments),'draft_plan',len(drafts))
