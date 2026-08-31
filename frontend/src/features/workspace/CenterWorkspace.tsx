import type { ReactNode } from "react";
import type { ConversationViewModel } from "../conversation";
import { ConversationView } from "../conversation";

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
