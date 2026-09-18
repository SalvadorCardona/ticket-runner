import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { LANGUAGES, setLanguage, useLanguage, useT, type Language } from "@/lib/i18n"

/* Which language the console is in, where the other settings are.
 *
 * The browser was asked first — and where it said nothing, the time zone was —
 * so this is not a question anybody has to answer: it is the answer, shown, and
 * a way to disagree with it. It used to be a flag at the right edge of the bar,
 * on every page, which is a lot of room for a thing you change once; a setting
 * belongs on the settings page, under the section that is about this console.
 *
 * It is not a key of `config.toml` and it is not saved with the section it sits
 * in: the language is this browser's, kept in `localStorage` like the theme, and
 * it takes the moment it is chosen. Hence a control of its own rather than a
 * field in the form beneath it.
 */
export function LanguagePicker() {
  const language = useLanguage()
  const t = useT()
  const chosen = LANGUAGES.find((item) => item.code === language) ?? LANGUAGES[0]

  return (
    <div className="mb-5 flex max-w-prose flex-col gap-1.5">
      <Label htmlFor="console-language">{t("the console's language")}</Label>
      <Select value={language} onValueChange={(value) => setLanguage(value as Language)}>
        <SelectTrigger id="console-language" className="w-full max-w-68">
          <SelectValue>
            <span aria-hidden className="mr-1.5">
              {chosen.flag}
            </span>
            {chosen.name}
          </SelectValue>
        </SelectTrigger>
        <SelectContent>
          {LANGUAGES.map((item) => (
            <SelectItem key={item.code} value={item.code}>
              <span aria-hidden>{item.flag}</span>
              {item.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <p className="text-muted-foreground text-xs leading-relaxed">
        {t(
          "This browser's, and this browser's only: it is not written to the file. Left alone, the console reads the one your browser asks for."
        )}
      </p>
    </div>
  )
}
