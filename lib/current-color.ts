/** Linear blue → cyan → green → yellow → orange → red current-density map. */
export function currentColor(fraction: number): string {
  const stops = [
    [0, 99, 235],
    [0, 180, 216],
    [19, 202, 70],
    [225, 233, 20],
    [255, 175, 0],
    [255, 60, 0],
  ]
  const position = Math.max(0, Math.min(1, fraction)) * (stops.length - 1)
  const stopIndex = Math.min(stops.length - 2, Math.floor(position))
  const blend = position - stopIndex
  const rgb = stops[stopIndex].map((channel, channelIndex) =>
    Math.round(
      channel + blend * (stops[stopIndex + 1][channelIndex] - channel),
    ),
  )
  return `#${rgb.map((channel) => channel.toString(16).padStart(2, "0")).join("")}`
}
