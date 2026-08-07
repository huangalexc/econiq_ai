import { Placeholder } from "@/components/placeholder";

export default function ProcessesPage() {
  return (
    <Placeholder title="Processes" issue="#21 (screener lives on Discover)">
      <p>
        The Process screener is on the Discover screen, where the ranking it
        filters already lives — ui_concept §25 describes it as a filtered view
        of the same ordering, and running it twice would let a Process be hot on
        one screen and absent from the other.
      </p>
      <p>
        This route becomes the saved-screen list once workspaces exist (#19).
      </p>
    </Placeholder>
  );
}
