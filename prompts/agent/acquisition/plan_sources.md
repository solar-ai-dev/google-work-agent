Return a JSON array of SourceFetchPlanV1 entries ordered by priority -- the array itself is the entire response, not a field inside a wrapper object. Use the supplied `retrieval_budget` (sources/pages/candidates/details remaining across all sources) as the hard ceiling for page, candidate, and detail-fetch limits. Never invent a larger budget or silently fall back to fixed maxima. Preserve user source/date/person/resource constraints. Return an empty array (`[]`) when selected resources already provide the required context and no additional source is needed; a deterministic downstream step reads that as NO_FETCH_NEEDED.

Each array entry is an object with exactly these fields -- no other field names (do not invent `query`, `fetch_budget`, or `justification`):
- schema_version: the fixed literal 1
- source: one of GMAIL, TASKS, CALENDAR
- priority: integer starting at 1 (lower runs first)
- reason_codes: array of strings explaining why this source is needed
- constraints: an object capturing the user's search/filter constraints for this source (query terms, date range, sender/person, resource id, etc.) in whatever key shape fits the source -- this is where free-form search intent belongs, not a separate `query` field
- page_size: integer, results per page for this source (>= 1)
- max_pages: integer, page count ceiling for this source (>= 0)
- max_candidates: integer, candidate count ceiling for this source (>= 0)
- detail_limit: integer, detail-fetch ceiling for this source (>= 0)
- required: boolean -- true when this source is necessary to answer the request, false when merely helpful
