import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  Input,
  Label,
  Text,
  Textarea,
} from '@/components/ui'
import {
  colorTokens,
  controlSizes,
  spaceTokens,
  textTokens,
} from '@/styles/tokens'

const colorClass: Record<(typeof colorTokens)[number], string> = {
  canvas: 'bg-canvas',
  surface: 'bg-surface',
  'surface-muted': 'bg-surface-muted',
  ink: 'bg-ink',
  'ink-muted': 'bg-ink-muted',
  line: 'bg-line',
  'line-subtle': 'bg-line-subtle',
  primary: 'bg-primary',
  accent: 'bg-accent',
  danger: 'bg-danger',
  warning: 'bg-warning',
  success: 'bg-success',
  info: 'bg-info',
}

export function DesignSystemPage() {
  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-12 px-6 py-12">
      <header className="flex flex-col gap-2">
        <Text variant="overline">Foundation</Text>
        <Text variant="display">Design system</Text>
        <Text variant="body" className="max-w-2xl text-ink-muted">
          Hard-corner tokens for a blue theme. Primary is #48AFF0. Components use
          a 0px radius and 1px borders.
        </Text>
      </header>

      <section className="flex flex-col gap-4">
        <Text variant="heading">Color</Text>
        <div className="grid grid-cols-2 gap-px border border-line bg-line sm:grid-cols-4">
          {colorTokens.map((token) => (
            <div key={token} className={`${colorClass[token]} p-4`}>
              <p
                className={`font-mono text-caption ${
                  token === 'canvas' ||
                  token === 'surface' ||
                  token === 'surface-muted' ||
                  token === 'line-subtle' ||
                  token === 'primary' ||
                  token === 'accent'
                    ? 'text-ink'
                    : 'text-surface'
                }`}
              >
                {token}
              </p>
            </div>
          ))}
        </div>
      </section>

      <section className="flex flex-col gap-4">
        <Text variant="heading">Text</Text>
        <div className="flex flex-col gap-3 border border-line bg-surface p-6">
          {textTokens.map((token) => (
            <Text key={token} variant={token}>
              {token} — The case file is complete.
            </Text>
          ))}
          <Text variant="mono">CASE-1042 · mono</Text>
        </div>
      </section>

      <section className="flex flex-col gap-4">
        <Text variant="heading">Spacing</Text>
        <div className="flex flex-col gap-2 border border-line bg-surface p-6">
          {spaceTokens.map((space) => (
            <div key={space} className="flex items-center gap-3">
              <span className="w-10 font-mono text-caption text-ink-muted">
                {space}
              </span>
              <div
                className="h-4 bg-primary"
                style={{ width: `${space * 4}px` }}
              />
            </div>
          ))}
        </div>
      </section>

      <section className="flex flex-col gap-4">
        <Text variant="heading">Size</Text>
        <div className="flex flex-wrap items-end gap-3">
          {controlSizes.map((size) => (
            <Button key={size} size={size}>
              Button {size}
            </Button>
          ))}
        </div>
        <div className="grid gap-4 md:grid-cols-3">
          {controlSizes.map((size) => (
            <Input key={size} size={size} placeholder={`Input ${size}`} />
          ))}
        </div>
      </section>

      <section className="flex flex-col gap-4">
        <Text variant="heading">Components</Text>
        <div className="flex flex-wrap gap-2">
          <Button variant="solid">Primary</Button>
          <Button variant="outline">Outline</Button>
          <Button variant="ghost">Ghost</Button>
          <Button variant="danger">Danger</Button>
        </div>
        <div className="flex flex-wrap gap-2">
          <Badge>Default</Badge>
          <Badge tone="muted">Muted</Badge>
          <Badge tone="accent">Primary</Badge>
          <Badge tone="success">Success</Badge>
          <Badge tone="warning">Warning</Badge>
          <Badge tone="danger">Danger</Badge>
          <Badge tone="info">Info</Badge>
        </div>
        <Card>
          <CardHeader>
            <Text variant="heading">Case card</Text>
          </CardHeader>
          <CardBody className="flex flex-col gap-3">
            <div className="flex flex-col gap-1">
              <Label htmlFor="case-id">Case id</Label>
              <Input id="case-id" placeholder="CASE-1042" />
            </div>
            <div className="flex flex-col gap-1">
              <Label htmlFor="notes">Notes</Label>
              <Textarea id="notes" placeholder="Evidence notes" />
            </div>
          </CardBody>
        </Card>
      </section>
    </div>
  )
}
