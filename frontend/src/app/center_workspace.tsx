import type { ReactNode } from "react";
import type { ConversationViewModel } from "../features/conversation";
import { ConversationView } from "../features/conversation";

export type CenterWorkspaceProps = {
  resourceViewer: ReactNode;
  conversationViewModel: ConversationViewModel;
};

export function CenterWorkspace({ resourceViewer, conversationViewModel }: CenterWorkspaceProps): JSX.Element {
  return (
    <main className="panel center-workspace">
      <ConversationView viewModel={conversationViewModel}>
        {resourceViewer}
      </ConversationView>
    </main>
  );
}
