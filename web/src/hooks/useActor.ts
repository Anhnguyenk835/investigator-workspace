import { useAuth } from '@/features/auth/AuthProvider'

/** Who this is, as the server labels them on notes and sign-offs: the signed-in email, or a demo name. */
export function useActor(): string {
  return useAuth().actor
}
