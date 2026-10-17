import { Link } from 'react-router-dom'
import { Button, Card, CardBody, CardHeader, Select } from '@/components/ui'
import { useToast } from '@/components/ui/Toast'
import { useTour } from '@/features/tour'
import { Field } from '@/components/shared/Field'
import { PageHeader } from '@/components/shared/PageHeader'
import { useAuth } from '@/features/auth/AuthProvider'
import { useSettings } from '@/hooks/useSettings'
import { TIMEZONES } from '@/lib/format'

export function SettingsPage() {
  const { timezone, setTimezone } = useSettings()
  const { mode, user } = useAuth()
  const tour = useTour()
  const toast = useToast()
  const zones: string[] = TIMEZONES.includes(timezone as (typeof TIMEZONES)[number]) ? [...TIMEZONES] : [timezone, ...TIMEZONES]

  return (
    <>
      <PageHeader title="Settings" description="Display preferences for this browser." />
      <div className="grid max-w-3xl gap-6">
        <Card data-tour="settings-account">
          <CardHeader>
            <h2 className="text-body font-medium">Account</h2>
          </CardHeader>
          <CardBody className="flex flex-col gap-2 text-body text-ink">
            {mode === 'user' ? (
              <>
                <p>{user?.name ?? 'Signed in with Google'}</p>
                <p className="text-caption text-ink-muted">{user?.email}</p>
                <p className="text-caption text-ink-muted">Your investigations, notes, chats, directory and connections are private to this account. Your name on notes and sign-offs is your email.</p>
              </>
            ) : mode === 'demo' ? (
              <p className="text-caption text-ink-muted">You are using the demo workspace with fictional data. Anything you create here is deleted after 24 hours. Sign in with Google to work on your own investigations.</p>
            ) : (
              <p className="text-caption text-ink-muted">Sign-in is turned off on this server, so everyone who can reach it is the same user.</p>
            )}
          </CardBody>
        </Card>

        <Card>
          <CardHeader>
            <h2 className="text-body font-medium">Display</h2>
          </CardHeader>
          <CardBody>
            <Field label="Timezone" hint="Timestamps across the product are shown in this timezone. Saved in this browser only.">
              <Select value={timezone} onChange={(e) => setTimezone(e.target.value)}>
                {zones.map((tz) => (
                  <option key={tz} value={tz}>
                    {tz}
                  </option>
                ))}
              </Select>
            </Field>
          </CardBody>
        </Card>

        <Card data-tour="help">
          <CardHeader>
            <h2 className="text-body font-medium">Help</h2>
          </CardHeader>
          <CardBody className="flex flex-col items-start gap-3 text-body text-ink">
            <p className="text-caption text-ink-muted">A short introduction, and a guide the first time you open each page.</p>
            <div className="flex flex-wrap gap-2">
              <Button variant="outline" onClick={tour.startIntro}>
                Take the introduction
              </Button>
              <Button
                variant="outline"
                onClick={() => {
                  tour.resetPages()
                  toast.success('Page guides reset', 'Each page shows its guide again the next time you open it.')
                }}
              >
                Show page guides again
              </Button>
            </div>
          </CardBody>
        </Card>

        <Card>
          <CardHeader>
            <h2 className="text-body font-medium">Data handling</h2>
          </CardHeader>
          <CardBody className="flex flex-col gap-2 text-body text-ink">
            <p>Sources are read with your own permissions and only while an investigation runs. Access tokens are stored encrypted on the server and never reach this browser.</p>
            <p>Customer-facing drafts are never sent from this product. A person must review and send them.</p>
            <p>Disconnecting a source removes the stored access token. Investigations you already ran keep the evidence they collected.</p>
            <Link to="/settings/connectors" className="mt-2 w-fit underline underline-offset-4 hover:text-info">
              Manage connectors
            </Link>
          </CardBody>
        </Card>
      </div>
    </>
  )
}
