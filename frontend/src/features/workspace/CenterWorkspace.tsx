import type { ConversationViewModel } from "../conversation";
import { ConversationView } from "../conversation";
import { ResourceDetail, type ResourceDetailProps } from "./ResourceDetail";

export type CenterWorkspaceProps = {
  resourceDetail: ResourceDetailProps;
  conversationViewModel: ConversationViewModel;
};

export function CenterWorkspace({ resourceDetail, conversationViewModel }: CenterWorkspaceProps): JSX.Element {
  return (
    <main className="panel center-workspace">
      <ConversationView viewModel={conversationViewModel}>
        <ResourceDetail {...resourceDetail} />
      </ConversationView>
    </main>
  );
}
