import { cva, type VariantProps } from 'class-variance-authority'
import { type HTMLAttributes } from 'react'
import { cn } from '@/lib/cn'

const badgeVariants = cva(
  'inline-flex items-center gap-1 whitespace-nowrap border px-1.5 py-px text-[0.625rem] font-medium uppercase leading-4 tracking-wide',
  {
    variants: {
      tone: {
        default: 'border-line bg-surface text-ink-muted',
        muted: 'border-line-subtle bg-surface-muted text-ink-muted',
        accent: 'border-primary/25 bg-primary/15 text-info',
        danger: 'border-danger/20 bg-danger/10 text-danger',
        warning: 'border-warning/20 bg-warning/10 text-warning',
        success: 'border-success/20 bg-success/10 text-success',
        info: 'border-info/20 bg-info/10 text-info',
        successSoft: 'border-success/20 bg-success/10 text-success',
        warningSoft: 'border-warning/20 bg-warning/10 text-warning',
        dangerSoft: 'border-danger/20 bg-danger/10 text-danger',
        infoSoft: 'border-info/20 bg-info/10 text-info',
      },
    },
    defaultVariants: {
      tone: 'default',
    },
  },
)

export type BadgeProps = HTMLAttributes<HTMLSpanElement> &
  VariantProps<typeof badgeVariants>

export function Badge({ className, tone, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ tone }), className)} {...props} />
}
