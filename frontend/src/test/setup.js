import '@testing-library/jest-dom/vitest'

// jsdom does not implement ResizeObserver (used by Recharts ResponsiveContainer)
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver = globalThis.ResizeObserver || ResizeObserverStub
