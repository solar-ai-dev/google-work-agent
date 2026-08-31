import { useRef, useState } from "react";
import { ApiClientError } from "../../api/client";
import { stageAttachment, type StagedAttachmentDescriptor } from "./api/stage_attachment";

export const MAX_ATTACHMENT_COUNT = 10;
export const MAX_ATTACHMENT_BYTES = 8 * 1024 * 1024;

export function AttachmentPicker({ disabled, onStaged }: { disabled: boolean; onStaged: (descriptors: StagedAttachmentDescriptor[]) => Promise<void> | void }): JSX.Element {
  const [message, setMessage] = useState<string | null>(null);
  const [staging, setStaging] = useState(false);
  const commandIdsRef = useRef(new Map<string, string>());

  async function selectFiles(files: FileList | null): Promise<void> {
    if (!files || files.length === 0) return;
    const selected = Array.from(files);
    const validationError = validateFiles(selected);
    if (validationError) {
      setMessage(validationError);
      return;
    }
    setStaging(true);
    setMessage(null);
    const descriptors: StagedAttachmentDescriptor[] = [];
    try {
      for (const [index, file] of selected.entries()) {
        const key = `${index}:${file.name}:${file.size}:${file.type}:${file.lastModified}`;
        let commandId = commandIdsRef.current.get(key);
        if (!commandId) {
          commandId = crypto.randomUUID();
          commandIdsRef.current.set(key, commandId);
        }
        descriptors.push(await stageAttachment(file, commandId));
        setMessage(`${descriptors.length}/${selected.length}개 파일을 준비했습니다.`);
      }
      await onStaged(descriptors);
      setMessage(`${descriptors.length}개 파일을 작업에 추가했습니다.`);
    } catch (error) {
      const reason = error instanceof ApiClientError ? error.message : "첨부파일을 준비하지 못했습니다.";
      setMessage(`${descriptors.length}/${selected.length}개 준비됨. ${reason} 같은 파일을 다시 선택하면 동일한 작업 ID로 안전하게 확인합니다.`);
    } finally {
      setStaging(false);
    }
  }

  return (
    <div>
      <label className="button-secondary">
        첨부파일 선택
        <input type="file" multiple hidden disabled={disabled || staging} onChange={(event) => { void selectFiles(event.currentTarget.files); event.currentTarget.value = ""; }} />
      </label>
      <div className="muted">최대 {MAX_ATTACHMENT_COUNT}개, 파일당 8 MB</div>
      {message ? <p role="status" className="muted">{message}</p> : null}
    </div>
  );
}

function validateFiles(files: File[]): string | null {
  if (files.length > MAX_ATTACHMENT_COUNT) return `첨부파일은 한 번에 최대 ${MAX_ATTACHMENT_COUNT}개까지 선택할 수 있습니다.`;
  for (const file of files) {
    if (file.size === 0) return `${file.name || "이름 없는 파일"}은 비어 있습니다.`;
    if (file.size > MAX_ATTACHMENT_BYTES) return `${file.name || "이름 없는 파일"}은 8 MB를 초과합니다.`;
    if (!file.name || file.name.length > 255 || file.name.includes("/") || file.name.includes("\\")) return "안전하지 않은 파일 이름은 사용할 수 없습니다.";
    if (!file.type || file.type.length > 255 || !file.type.includes("/") || /[\r\n]/.test(file.type)) return `${file.name}의 파일 형식을 확인할 수 없습니다.`;
  }
  return null;
}
