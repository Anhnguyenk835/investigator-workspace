import { Link } from 'react-router-dom'
import { Text } from '@/components/ui'

export function NotFoundPage() {
  return (
    <section className="mx-auto flex max-w-3xl flex-col gap-4 px-6 py-16">
      <Text variant="overline">404</Text>
      <Text variant="title">Page not found</Text>
      <Link to="/" className="text-body underline underline-offset-4">
        Back to workspace
      </Link>
    </section>
  )
}
