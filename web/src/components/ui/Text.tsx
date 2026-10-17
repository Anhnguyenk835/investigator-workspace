import { cva, type VariantProps } from 'class-variance-authority'
import { type ElementType, type HTMLAttributes } from 'react'
import { cn } from '@/lib/cn'

const textVariants = cva('text-ink', {
  variants: {
    variant: {
      display: 'font-sans text-display',
      title: 'font-sans text-title',
      heading: 'font-sans text-heading',
      body: 'font-sans text-body',
      caption: 'font-sans text-caption text-ink-muted',
      overline: 'font-sans text-overline uppercase text-ink-muted',
      mono: 'font-mono text-caption',
    },
  },
  defaultVariants: {
    variant: 'body',
  },
})

const defaultTags = {
  display: 'h1',
  title: 'h2',
  heading: 'h3',
  body: 'p',
  caption: 'p',
  overline: 'p',
  mono: 'code',
} as const

export type TextProps = HTMLAttributes<HTMLElement> &
  VariantProps<typeof textVariants> & {
    as?: ElementType
  }

export function Text({ className, variant = 'body', as, ...props }: TextProps) {
  const Component = as ?? defaultTags[variant ?? 'body']

  return (
    <Component className={cn(textVariants({ variant }), className)} {...props} />
  )
}
