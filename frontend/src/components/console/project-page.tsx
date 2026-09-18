import { ArrowLeft } from "lucide-react"
import { ActionList } from "react-data-form"
import {
  Link,
  ResourceViewButton,
  generateLinkByResource,
  useCurrentViewResourceContext,
} from "react-resource-view"

import { Skeleton } from "@/components/ui/skeleton"
import { useT } from "@/lib/i18n"
import { isAPage, type ProjectItem } from "@/resources/projects"
import { settingsHref } from "@/resources/settings"

import { Eyebrow, Fact, Facts } from "./frame"
import { Markdown } from "./markdown"
import { Away, Chip } from "./ticket-bits"

/* One project, as a page.
 *
 * The `read` view of the projects resource: what the card said, and then the
 * thing a card has no room for — the brief. Which is the reason to open a
 * project at all: it is not a description of the project, it is what every
 * ticket of that project is told before it is told the ticket.
 *
 * The gesture the page exists for is the *edit* button, and it is the
 * package's own: the same form, the same drawer and the same toast as
 * everywhere else in the console. A project the configuration alone names has
 * no page to write to — it is a line in `config.toml` — so it gets the way to
 * the settings instead of a button that could only fail.
 */

export function ProjectPage() {
  const context = useCurrentViewResourceContext()
  const project = context.data as ProjectItem | undefined
  const t = useT()

  const back = generateLinkByResource({
    resource: context.resource,
    resourceAction: ActionList.list,
  })
  const page = project ? isAPage(project.id) : false

  return (
    <div className="min-w-0">
      <div className="mb-4 flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <Link
          to={back}
          className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-xs"
        >
          <ArrowLeft className="size-3.5" />
          {t("projects")}
        </Link>
        <span className="flex-1" />
        {project?.url ? <Away label="Notion" href={project.url} /> : null}
      </div>

      {!project ? (
        context.error ? (
          <p className="text-destructive text-sm">{t("This project could not be read.")}</p>
        ) : (
          <div className="flex flex-col gap-2">
            <Skeleton className="h-8 w-2/3" />
            <Skeleton className="mt-2 h-20 w-full" />
            <Skeleton className="h-3 w-full" />
          </div>
        )
      ) : (
        <>
          <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-3">
            <div className="min-w-0">
              <Eyebrow>{project.work}</Eyebrow>
              <h2 className="mt-1 text-xl leading-tight font-bold tracking-[-0.02em] text-balance sm:text-2xl">
                {project.name}
              </h2>
            </div>
            {page ? (
              <ResourceViewButton
                action={ActionList.update}
                resource={context.resource}
                id={project.id}
                data={project}
              />
            ) : null}
          </div>

          <div className="mt-3 flex flex-wrap items-center gap-1.5">
            {project.tickets ? (
              <Chip>{t("{{count}} ticket(s)", { count: String(project.tickets) })}</Chip>
            ) : null}
            {project.source === "config" ? <Chip>{t("from the configuration")}</Chip> : null}
            {project.configured && project.source === "board" ? (
              <Chip>{t("path set in the configuration")}</Chip>
            ) : null}
          </div>

          <Facts className="mt-4">
            <Fact label={t("repository")}>
              <span className="font-mono text-xs">{project.repository || "—"}</span>
            </Fact>
            <Fact label={t("on this machine")}>
              <span className="font-mono text-xs">
                {project.where || t("wherever the clone is")}
              </span>
            </Fact>
          </Facts>

          {page ? (
            <div className="mt-6">
              <Eyebrow>{t("the brief")}</Eyebrow>
              <div className="mt-2">
                {project.content ? (
                  <Markdown text={project.content} />
                ) : (
                  <p className="text-muted-foreground text-sm">
                    {t(
                      "Nothing is written on this page, so its tickets are told about the workspace and nothing about the project."
                    )}
                  </p>
                )}
              </div>
            </div>
          ) : (
            <p className="text-muted-foreground mt-6 max-w-prose text-sm leading-relaxed">
              {t(
                "This project is a line in config.toml and has no page: the board has never heard of it, so there is nothing here to write a brief on."
              )}{" "}
              <Link to={settingsHref("projects")} className="underline underline-offset-2">
                {t("Change its path in the settings.")}
              </Link>
            </p>
          )}
        </>
      )}
    </div>
  )
}
