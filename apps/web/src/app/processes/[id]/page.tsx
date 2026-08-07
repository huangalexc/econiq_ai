import { Placeholder } from "@/components/placeholder";

export default function ProcessPage() {
  return (
    <Placeholder title="Process screen" issue="#23">
      <p>
        Overview, State history, State distribution, evidence timeline and the
        dependency graph, synchronised on one Process.
      </p>
      <p>
        The API behind it is ready — <code>/api/processes/{"{id}"}</code>,{" "}
        <code>/timeline</code>, <code>/states</code>, <code>/critiques</code> and{" "}
        <code>/journal</code> all serve this screen and all accept{" "}
        <code>as_of</code>.
      </p>
    </Placeholder>
  );
}
