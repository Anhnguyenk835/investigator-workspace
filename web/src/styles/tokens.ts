export const colorTokens = [
  'canvas',
  'surface',
  'surface-muted',
  'ink',
  'ink-muted',
  'line',
  'line-subtle',
  'primary',
  'accent',
  'danger',
  'warning',
  'success',
  'info',
] as const

export const textTokens = [
  'display',
  'title',
  'heading',
  'body',
  'caption',
  'overline',
] as const

export const spaceTokens = [0, 1, 2, 3, 4, 5, 6, 8, 10, 12, 16] as const

export const controlSizes = ['sm', 'md', 'lg'] as const

export const radiusPolicy = {
  default: 0,
  components: 0,
  full: 0,
} as const
