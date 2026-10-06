import { expect, test } from "bun:test"
import { parseCurrentAmps, parseResistanceOhms } from "lib/index"

test("current units are strict signed peak amperes including scientific notation", () => {
  for (const [input, expected] of [
    ["5mA", 0.005],
    ["0.1A", 0.1],
    ["250uA", 0.00025],
    ["250µA", 0.00025],
    ["250μA", 0.00025],
    ["10nA", 1e-8],
    [" -5 mA ", -0.005],
    ["1e-1A", 0.1],
    ["0", 0],
    [0.25, 0.25],
  ] as const)
    expect(parseCurrentAmps(input)).toBeCloseTo(expected, 12)
  for (const input of [
    "",
    "mA",
    "5MA",
    "5m",
    "5mA junk",
    "Infinity",
    "1e400A",
    "1V",
    Number.NaN,
  ])
    expect(() => parseCurrentAmps(input)).toThrow()
})

test("impedances accept positive real ohms and reject shorts, reactive values and garbage", () => {
  expect(parseResistanceOhms("50ohm")).toBe(50)
  expect(parseResistanceOhms("1kΩ")).toBe(1000)
  expect(parseResistanceOhms("2MOhm")).toBe(2e6)
  for (const input of [0, -1, Infinity, "50+j10", "50mA", "", "50ohm junk"])
    expect(() => parseResistanceOhms(input)).toThrow()
})
