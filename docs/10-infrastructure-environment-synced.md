# 10. Google Work Agent · 인프라 · 환경 설정 설계서

> **상태:** Draft v2.5 · **OS:** Windows 11 x64 · **Browser:** Chrome·Edge

## 1. 확정 결정

- 사용자별 설치, 관리자 권한 불필요
- One-folder Application Bundle + Windows Installer
- Launcher → FastAPI → MCP `stdio`
- UI·API same-origin, `127.0.0.1` 동적 Port
- API_ONLY·LOCAL_CAPABLE Artifact 분리
- P0 수동 In-place Upgrade
- 배포 Test·Production Code Signing 필수
- Ollama는 사용자 설치 외부 Runtime
- Backup 최근 5개·최대 30일

## 2. 지원 환경

API_ONLY 최소:
- x64 4 Core, RAM 8 GB, 여유 2 GB
- GPU·Ollama 불필요

LOCAL_CAPABLE:
- 지원 Ollama Version·승인 Model
- GPU Profile은 13의 평가 Gate로 확정
- 기준 미달은 API_LLM 고정

## 3. Process

```text
GoogleWorkAgentLauncher.exe
└─ GoogleWorkAgentService.exe
   └─ GoogleWorkMcpServer.exe

외부
└─ ollama.exe
```

Launcher가 Service를, Service가 MCP를 소유한다. Browser 종료는 Runtime 종료가 아니다. 제품은 Ollama를 시작·종료·업데이트하지 않는다.

## 4. Startup

```text
Single Instance Lock
→ Manifest·Signature 검증
→ Data Directory·ACL
→ Dynamic Port
→ Bootstrap Secret·Service Instance ID
→ FastAPI 시작
→ /health/live
→ SQLite·Migration·Domain·Keyring Adapter
→ Frontend Asset·API Contract·MCP Handshake·Tool Schema
→ /health/ready
→ Chrome·Edge Browser 열기
→ Local Session
→ /api/v1/runtime에서 Google·API LLM·Ollama·Model 진단
```

## 5. SEC-INF 계약

- `SEC-INF-001`: 127.0.0.1 only, dynamic Port, same-origin
- `SEC-INF-002`: Bootstrap CSPRNG 256-bit, 1회, 60초, Fragment
- `SEC-INF-003`: HttpOnly SameSite=Strict, Service restart invalidation
- `SEC-INF-004`: Host·Origin·Fetch Metadata·Session·Schema·Command ID·Version
- `SEC-INF-005`: OAuth Loopback dynamic listener
- `SEC-INF-006`: dev·staging·prod OAuth/Keyring/Build 분리
- `SEC-INF-007`: Keyring Namespace `GoogleWorkAgent/<env>/<credential-type>`
- `SEC-INF-008`: Google Token은 MCP, LLM Key는 LLM Adapter
- `SEC-INF-009`: ACL current user + SYSTEM
- `SEC-INF-010`: MCP absolute path·signature·hash·schema pin
- `SEC-INF-011`: Child environment allowlist
- `SEC-INF-012`: distributed test·production signing
- `SEC-INF-013`: signed release manifest
- `SEC-INF-014`: manual upgrade·downgrade block
- `SEC-INF-015`: backup excludes secrets and raw Google data
- `SEC-INF-016`: diagnostic allowlist
- `SEC-INF-017`: graceful shutdown
- `SEC-INF-018`: crash recovery
- `SEC-INF-019`: Ollama isolation
- `SEC-INF-020`: production secret file/env/CLI prohibition

## 6. Directory

```text
%LOCALAPPDATA%/Programs/GoogleWorkAgent/
├─ launcher
├─ service
├─ frontend
├─ mcp
├─ runtime
├─ schemas
├─ migrations
├─ manifests
└─ uninstaller

%LOCALAPPDATA%/GoogleWorkAgent/
├─ data
├─ backups
├─ settings
├─ logs
├─ diagnostics
├─ runtime
└─ cache
```

## 7. Config

Production precedence:
```text
Launcher Runtime Argument
→ Signed Build Config
→ User Settings
→ Product Default
```

Production Secret은 `.env`, JSON, Manifest, CLI에 넣지 않는다.

## 8. Installer

- Python Runtime·React Build 포함
- Node.js·Vite Dev Server 제외
- API_ONLY에는 Ollama·Model·GPU Library 제외
- LOCAL_CAPABLE에는 Adapter·GPU 진단·Model Manifest만 포함
- Upgrade 시 DB·Backup·Settings 보존

## 9. Upgrade·Migration

```text
정상 종료
→ Signature·Version
→ Pre-migration Backup
→ Program File 교체
→ Migration
→ quick_check·Contract 검사
→ 정상 시작
```

Migration 실패: Safe Mode, 자동 반복 금지, Backup 보존, 오래된 App 강제 Open 금지.

## 10. Backup·Restore

- Migration·Restore·Repair 전 Backup
- 최근 5개·최대 30일
- Restore는 앱 종료 상태에서 Manifest·Hash·quick_check·Schema 검증
- Token·Key·Session·Cache·Gmail 원문 제외

## 11. Health·Safe Mode

- `GET /health/live`: Process 응답
- `GET /health/ready`: Manifest·Assets·API Contract·SQLite·Migration·Domain·Keyring Adapter 접근·MCP Executable·Tool Schema. Credential·API Key·Ollama·Model 존재 여부는 포함하지 않는다.
- `GET /api/v1/runtime`: Session 이후 Google·LLM·Ollama 상세

Safe Mode 허용: 진단, Backup, Restore, Log, Settings, Shutdown
Safe Mode 금지: 새 Run, 승인, Write, Migration 재시도

## 12. Runtime Limit

```text
Service Start 30s
Shutdown 30s
MCP Start 10s
MCP Restart 1회
Google Read·Write 30s
API LLM 120s
Ollama 180s
SQLite busy_timeout 5s
LLM concurrency 1
MCP Read concurrency 3
Write concurrency 1
Conversation Active Run 1
```

## 13. Uninstall

기본 삭제:
- Program File·Shortcut
- Google OAuth Refresh Token
- LLM API Key
- Local Session·Bootstrap

기본 보존:
- SQLite DB·Backup·Settings

완전 삭제는 보존 데이터·Log·Diagnostic까지 삭제한다.

## 14. 설정 Schema

| Key | Type·Default | 변경 규칙 |
|---|---|---|
| `config_schema_version` | int, 1 | Migration만 변경 |
| `deployment_profile` | API_ONLY·LOCAL_CAPABLE | Build 고정 |
| `requested_runtime_mode` | API_LLM·AUTO·LOCAL_GPU | Active Run 중 금지 |
| `default_calendar_id` | string? | 설정 화면 |
| `default_tasklist_id` | string? | 설정 화면 |
| `timezone` | IANA string | Active Run 중 다음 Run부터 |
| `work_hours` | JSON, 평일 09:00~18:00 | Schema 검증 |
| `approval_ttl_minutes` | int, 30 | 5..120 |
| `run_retention_days` | int, 30 | 상한 확대 P1 |
| `external_llm_consent` | bool, false | API 전송 전 필수 |
| `ollama_endpoint` | loopback URL | LOCAL_CAPABLE만 |
| `approved_model_id` | signed manifest value | 사용자 임의 입력 금지 |
| `log_level` | INFO | Production DEBUG 임시만 |

Secret은 이 Schema에 포함하지 않는다.

## 15. Launcher 상태 Machine

```text
STOPPED
→ VALIDATING_ARTIFACTS
→ ACQUIRING_INSTANCE
→ STARTING_SERVICE
→ WAITING_LIVE
→ WAITING_READY
→ OPENING_BROWSER
→ RUNNING
→ STOPPING
→ STOPPED
```

예외 상태: `SAFE_MODE`, `START_FAILED`, `SHUTDOWN_TIMEOUT`.

- Single Instance Lock은 현재 Windows 사용자 범위다.
- 두 번째 실행은 사용자 전용 Named Pipe로 기존 Instance에 `OPEN_UI`를 요청한다.
- Stale Lock은 Process ID·Start Time·Pipe 응답을 모두 확인한 뒤 정리한다.
- Port·Bootstrap Secret은 상속된 제한 Handle 또는 보호된 IPC로 전달하며 CLI에 노출하지 않는다.
- Service Exit Code는 정상 종료, Safe Mode, Migration 실패, Manifest 실패, 강제 종료를 구분한다.

## 16. Service–MCP Handshake

Service는 MCP Child 시작 시 Tool Manifest Version과 함께 Process Memory용 256-bit Session Key를 제한된 stdin Handshake로 전달한다. 재시작마다 새 Key를 생성하며 환경 변수·파일·CLI에 저장하지 않는다.

## 17. Schema·Tool Startup 계약
- Domain DB Schema 목표는 v1.4이며 `0001` v1.2 baseline → `0002_action_effect_send_delete.sql` v1.3 → `0003_action_cancelled.sql` v1.4 순서로 적용한다.
- Startup Tool Registry 검증은 승인형 `gmail_send`, Task 완료 UPDATE, `calendar_delete_event`, 참석자 UPDATE를 허용하고 Gmail 원문 삭제·Task 삭제·반복 Event 전체 일괄 수정은 차단한다.
- Migration 후 `PRAGMA foreign_key_check`와 Tool Schema Version 검증을 통과해야 Write를 허용한다.
