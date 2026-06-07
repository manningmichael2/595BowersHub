import { useAuthStore } from '../stores/auth'
import LoginPage from '../pages/LoginPage'

interface Props {
  children: React.ReactNode
}

export default function AuthGate({ children }: Props) {
  const { user } = useAuthStore()

  if (!user) {
    return <LoginPage />
  }

  return <>{children}</>
}
