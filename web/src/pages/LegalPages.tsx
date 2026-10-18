import { type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { Icon } from '@/components/ui'

const CONTACT = 'anh.tuan.nguyen@c0x12c.com'
const UPDATED = 'October 18, 2026'

interface Section {
  title: string
  body: ReactNode[]
}

function LegalLayout({ title, intro, sections }: { title: string; intro: string; sections: Section[] }) {
  return (
    <main className="min-h-dvh bg-canvas px-4 py-10">
      <article className="mx-auto w-full max-w-3xl border border-line bg-surface p-6 sm:p-10">
        <Link to="/login" className="inline-flex items-center gap-2 text-caption text-ink-muted hover:text-ink hover:underline">
          <Icon name="search" className="size-3.5" /> The Investigator
        </Link>
        <h1 className="mt-4 text-title text-ink">{title}</h1>
        <p className="mt-1 text-caption text-ink-muted">Last updated {UPDATED}</p>
        <p className="mt-5 text-body text-ink">{intro}</p>
        {sections.map((s) => (
          <section key={s.title} className="mt-8">
            <h2 className="text-body font-medium text-ink">{s.title}</h2>
            <div className="mt-2 flex flex-col gap-3 text-body text-ink-muted">{s.body}</div>
          </section>
        ))}
        <nav aria-label="Legal" className="mt-10 flex gap-4 border-t border-line-subtle pt-4 text-caption text-ink-muted">
          <Link to="/privacy" className="hover:text-ink hover:underline">
            Privacy Policy
          </Link>
          <Link to="/terms" className="hover:text-ink hover:underline">
            Terms of Service
          </Link>
        </nav>
      </article>
    </main>
  )
}

function List({ items }: { items: string[] }) {
  return (
    <ul className="flex list-disc flex-col gap-1.5 pl-5">
      {items.map((i) => (
        <li key={i}>{i}</li>
      ))}
    </ul>
  )
}

const contact = (
  <p>
    Questions, or a request to delete your data:{' '}
    <a className="text-ink underline underline-offset-2" href={`mailto:${CONTACT}`}>
      {CONTACT}
    </a>
    .
  </p>
)

export function PrivacyPage() {
  return (
    <LegalLayout
      title="Privacy Policy"
      intro="The Investigator helps a customer success team reconstruct what happened in an escalation from the evidence in its own tools. This page says what the app collects, why, and how you can remove it."
      sections={[
        {
          title: 'What we collect',
          body: [
            <List
              key="a"
              items={[
                'Sign in with Google: your email address, name and profile picture, from the openid, email and profile scopes. Used only to identify your account.',
                'Use with mock data: no account. A temporary session cookie, and the investigations and questions you make in that sandbox.',
                'Your work: the investigations you start, the questions you ask and the answers given, your notes, and the customers, projects and people you add to the directory.',
                'Connected sources (optional): if you connect Gmail, Slack, Jira, Confluence or Notion, you give the app read access. It reads them only when you run an investigation, and keeps the records it used as evidence in that investigation. Gmail uses the read-only scope (gmail.readonly).',
              ]}
            />,
          ],
        },
        {
          title: 'How we use it',
          body: [
            <p key="a">Only to run the investigations you ask for and to show you the results. We do not sell your data, use it for advertising, or build profiles of you.</p>,
            <p key="b">
              The app&apos;s use and transfer of information received from Google APIs adheres to the Google API Services User Data Policy, including the Limited Use requirements.
            </p>,
          ],
        },
        {
          title: 'AI processing',
          body: [
            <p key="a">
              To write answers, the app sends the text of your question and the evidence it found to AI model providers (Google Gemini, OpenAI or Anthropic) through its own gateway. Automated checks look for secrets and prompt-injection attempts in that text. Do not connect sources or enter material you are not allowed to process this way.
            </p>,
          ],
        },
        {
          title: 'Storage and security',
          body: [
            <p key="a">Data is stored in a database hosted on Google Cloud and sent over HTTPS. Access tokens for connected sources are encrypted before they are stored. Everything you create is private to your account.</p>,
          ],
        },
        {
          title: 'Cookies',
          body: [<p key="a">One session cookie keeps you signed in. It is not readable by scripts on the page. There are no advertising or analytics cookies.</p>],
        },
        {
          title: 'Keeping and deleting your data',
          body: [
            <List
              key="a"
              items={[
                'Mock-data sandboxes, with their investigations and chats, are deleted after 24 hours.',
                'Signed-in data is kept until you remove it. You can delete chats and directory entries yourself, and disconnect a source at any time, which revokes the access you gave.',
                'To delete your account and everything under it, write to the address below.',
              ]}
            />,
          ],
        },
        { title: 'Contact', body: [contact] },
      ]}
    />
  )
}

export function TermsPage() {
  return (
    <LegalLayout
      title="Terms of Service"
      intro="The Investigator is a demonstration project. By signing in or using it with mock data you agree to these terms."
      sections={[
        {
          title: 'The service',
          body: [<p key="a">The app is offered as is, without warranty, and may change, be limited or be taken offline at any time. Do not rely on it as the only record of a business decision.</p>],
        },
        {
          title: 'AI can be wrong',
          body: [<p key="a">Answers are written by AI models from the evidence found. Each claim should point to a record you can open; check it before acting. When the evidence does not say, the app should say it is unknown.</p>],
        },
        {
          title: 'Your use',
          body: [
            <List
              key="a"
              items={[
                'Use only data you are allowed to process, and only sources you have the right to connect.',
                'Do not try to disrupt the service, get around its limits, or access anyone else’s data.',
                'Usage limits apply to the demo (investigations, questions and sessions) and may change.',
              ]}
            />,
          ],
        },
        {
          title: 'Your data',
          body: [
            <p key="a">
              You keep the rights to what you bring in. How it is handled is described in the{' '}
              <Link to="/privacy" className="text-ink underline underline-offset-2">
                Privacy Policy
              </Link>
              .
            </p>,
          ],
        },
        {
          title: 'Liability',
          body: [<p key="a">To the extent the law allows, the operator is not liable for losses arising from use of the app or from its answers.</p>],
        },
        { title: 'Contact', body: [contact] },
      ]}
    />
  )
}
