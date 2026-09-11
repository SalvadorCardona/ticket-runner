import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
} from "@/components/ui/select"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { LANGUAGES, setLanguage, useLanguage, useT, type Language } from "@/lib/i18n"

/* Which language the console is in, at the right edge of the bar.
 *
 * The browser was asked first — and where it said nothing, the time zone was —
 * so this is not a question anybody has to answer: it is the answer, shown, and
 * a way to disagree with it. The flag is what the eye finds at that size; the
 * two letters beside it are for the screen that draws a flag as two squares,
 * and for the reader who does not read a flag as a language.
 */
export function LanguagePicker() {
  const language = useLanguage()
  const t = useT()
  const chosen = LANGUAGES.find((item) => item.code === language) ?? LANGUAGES[0]
  const label = t("the console's language")

  return (
    <Select value={language} onValueChange={(value) => setLanguage(value as Language)}>
      <Tooltip>
        <TooltipTrigger asChild>
          <SelectTrigger
            size="sm"
            aria-label={label}
            className="gap-1.5 border-0 px-2 shadow-none"
          >
            <span aria-hidden className="text-sm leading-none">
              {chosen.flag}
            </span>
            <span className="text-muted-foreground font-mono text-[0.7rem] uppercase">
              {chosen.code}
            </span>
          </SelectTrigger>
        </TooltipTrigger>
        <TooltipContent>{label}</TooltipContent>
      </Tooltip>
      <SelectContent align="end">
        {LANGUAGES.map((item) => (
          <SelectItem key={item.code} value={item.code}>
            <span aria-hidden>{item.flag}</span>
            {item.name}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}
