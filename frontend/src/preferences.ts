export const TIMEFRAMES = ['Daily', '4H', '1H', '15M', '5M'] as const;
export const TIMEZONES = [
  { value: 'Asia/Qatar', label: 'Qatar' },
  { value: 'Asia/Kolkata', label: 'India' },
  { value: 'UTC', label: 'UTC' },
  { value: 'Europe/London', label: 'London' },
  { value: 'America/New_York', label: 'New York' },
] as const;

export function validateDisplayTimezone(value: string): string {
  if (!TIMEZONES.some((zone) => zone.value === value)) {
    throw new Error('Unsupported display timezone');
  }
  return value;
}

export function formatTimestamp(timestamp: string, timeZone: string): string {
  if (!timestamp.endsWith('Z') || !Number.isFinite(Date.parse(timestamp))) {
    throw new Error('Timestamp must be a valid UTC ISO string ending in Z');
  }
  return new Intl.DateTimeFormat('en-GB', {
    timeZone: validateDisplayTimezone(timeZone),
    dateStyle: 'medium',
    timeStyle: 'long',
    hour12: false,
  }).format(new Date(timestamp));
}
