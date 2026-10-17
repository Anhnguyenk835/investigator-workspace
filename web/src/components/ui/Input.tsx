import { cva, type VariantProps } from 'class-variance-authority'
import { type InputHTMLAttributes, forwardRef } from 'react'
import { cn } from '@/lib/cn'

const inputVariants = cva(
  'w-full border border-line bg-surface text-ink focus:border-ink-muted/40 focus:outline-none focus-visible:outline-none placeholder:text-ink-muted disabled:cursor-not-allowed disabled:opacity-40',
  {
    variants: {
      size: {
        sm: 'h-control-sm px-3 text-caption',
        md: 'h-control-md px-3 text-body',
        lg: 'h-control-lg px-4 text-body',
      },
    },
    defaultVariants: {
      size: 'md',
    },
  },
)

export type InputProps = Omit<InputHTMLAttributes<HTMLInputElement>, 'size'> &
  VariantProps<typeof inputVariants>

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { className, size, type = 'text', ...props },
  ref,
) {
  return (
    <input
      ref={ref}
      type={type}
      className={cn(inputVariants({ size }), className)}
      {...props}
    />
  )
})
