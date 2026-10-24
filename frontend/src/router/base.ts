export function getRouterBase(pathname: string): string {
  const prefix = pathname.match(/^\/(spa|app)(?:\/|$)/)
  return prefix ? `/${prefix[1]}/` : '/'
}
