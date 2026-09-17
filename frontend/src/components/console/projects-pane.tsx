import * as React from "react"
import { FolderGit2, RefreshCw } from "lucide-react"

import { Button } from "@/components/ui/button"
import { api, why } from "@/lib/api"
import { useT } from "@/lib/i18n"
import type { Project, Projects } from "@/lib/types"

import { Eyebrow, Fact, Facts, PageHead, Panel } from "./frame"
import { Chip } from "./ticket-bits"

/* Every project this installation knows of.
 *
 * `ticket-runner projects` says the same thing in a terminal, and until now the
 * console said nothing at all: the board showed a project's *name* on a card and
 * offered no way of asking what that name pointed at. Which is the question you
 * have when a ticket comes back "no repository could be found".
 *
 * Three sources, drawn as one list because that is how somebody thinks of their
 * projects: the board's own database, the `[projects]` table of the
 * configuration, and where the repository turned out to be. A row says which of
 * them it came from, and a project the board has never heard of is marked as
 * the file's — so nobody goes looking for a page that does not exist.
 *
 * Nothing is written from here. A project is a page, and the way to change one
 * is to open it — which is what the link on its name is for, where there is one.
 */

function Row({ project }: { project: Project }) {
  const t = useT()
  const declared = project.repository || project.path || project.configured
  return (
    <Panel
      eyebrow={project.kind === "code" ? t("code work") : t("document work")}
      title={
        project.url ? (
          <a
            href={project.url}
            target="_blank"
            rel="noreferrer noopener"
            className="underline-offset-2 hover:underline"
          >
            {project.name}
          </a>
        ) : (
          project.name
        )
      }
      action={
        project.tickets ? (
          <span className="text-muted-foreground font-mono text-xs tabular-nums">
            {t("{{count}} ticket(s)", { count: String(project.tickets) })}
          </span>
        ) : null
      }
    >
      {declared ? (
        <Facts>
          <Fact label={t("repository")}>
            <span className="font-mono text-xs">{project.repository || "—"}</span>
          </Fact>
          <Fact label={t("on this machine")}>
            <span className="font-mono text-xs">
              {project.configured || project.path || t("wherever the clone is")}
            </span>
          </Fact>
        </Facts>
      ) : (
        <p className="text-muted-foreground text-sm">
          {t(
            "Nothing declares a repository, so its tickets produce a document rather than a pull request."
          )}
        </p>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-1.5">
        {project.source === "config" ? <Chip>{t("from the configuration")}</Chip> : null}
        {project.configured && project.source === "board" ? (
          <Chip>{t("path set in the configuration")}</Chip>
        ) : null}
      </div>
    </Panel>
  )
}

export function ProjectsPane() {
  const t = useT()
  const [drawn, setDrawn] = React.useState<Projects | null>(null)
  const [problem, setProblem] = React.useState("")

  const load = React.useCallback(async () => {
    try {
      setDrawn(await api.projects())
      setProblem("")
    } catch (error) {
      setProblem(why(error))
    }
  }, [])

  React.useEffect(() => {
    void load()
  }, [load])

  const rows = drawn?.projects ?? []
  const code = rows.filter((project) => project.kind === "code").length

  return (
    <div className="p-3.5 sm:p-5">
      <PageHead
        crumbs={[t("workspace"), t("projects")]}
        title={t("What the tickets are about.")}
        blurb={t(
          "A project says where the work happens and what conventions hold there. One with no repository is not a mistake: its tickets come back as a document."
        )}
        action={
          <Button variant="outline" size="sm" onClick={() => void load()}>
            <RefreshCw />
            {t("Reread")}
          </Button>
        }
      >
        <span className="text-muted-foreground inline-flex items-center gap-1.5 font-mono text-[0.7rem]">
          <FolderGit2 className="size-3.5" />
          {rows.length
            ? t("{{count}} of {{total}} on a repository", {
                count: String(code),
                total: String(rows.length),
              })
            : t("nothing yet")}
        </span>
      </PageHead>

      {problem ? (
        <p className="text-tr-amber border-tr-amber/30 bg-tr-amber/10 rounded-xl border px-4 py-3 text-sm">
          {problem}
        </p>
      ) : !drawn ? (
        <p className="text-muted-foreground text-sm">{t("Reading the projects…")}</p>
      ) : !rows.length ? (
        <p className="text-muted-foreground rounded-xl border border-dashed px-4 py-10 text-center text-sm">
          {t("No project yet — a ticket without one comes back as a document.")}
        </p>
      ) : (
        <div className="space-y-3">
          {rows.map((project) => (
            <Row key={project.id || project.name} project={project} />
          ))}
        </div>
      )}

      {drawn ? (
        <p className="text-muted-foreground mt-4 text-xs">
          <Eyebrow>runner.workspace_root</Eyebrow> —{" "}
          <span className="font-mono">{drawn.workspace_root}</span>{" "}
          {t("is where a repository is looked for, and cloned into when it is nowhere.")}
        </p>
      ) : null}
    </div>
  )
}
