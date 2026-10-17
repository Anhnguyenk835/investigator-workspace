import { cva, type VariantProps } from 'class-variance-authority'
import { type ButtonHTMLAttributes, forwardRef } from 'react'
import { cn } from '@/lib/cn'

const buttonVariants = cva(
  'inline-flex items-center justify-center gap-2 border border-transparent font-medium transition-colors disabled:pointer-events-none disabled:opacity-40',
  {
    variants: {
      variant: {
        solid:
          'border-primary bg-primary text-primary-fg hover:bg-primary/90',
        outline: 'border-line bg-surface text-ink hover:bg-surface-muted',
        ghost:
          'border-transparent bg-transparent text-ink hover:bg-surface-muted',
        accent:
          'border-primary bg-primary text-primary-fg hover:bg-primary/90',
        danger: 'border-danger/30 bg-danger/10 text-danger hover:bg-danger/20',
      },
      size: {
        sm: 'h-control-sm px-3 text-caption',
        md: 'h-control-md px-4 text-body',
        lg: 'h-control-lg px-5 text-body',
      },
    },
    defaultVariants: {
      variant: 'solid',
      size: 'md',
    },
  },
)

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> &
  VariantProps<typeof buttonVariants>

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  function Button({ className, variant, size, type = 'button', ...props }, ref) {
    return (
      <button
        ref={ref}
        type={type}
        className={cn(buttonVariants({ variant, size }), className)}
        {...props}
      />
    )
  },
)
