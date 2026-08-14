import "@testing-library/jest-dom";

// CodeMirror measures text via Range.getClientRects()/getBoundingClientRect();
// jsdom does not implement them. Provide minimal stubs so the editor can mount
// inside tests without throwing.
if (!Range.prototype.getClientRects) {
  Range.prototype.getClientRects = () => ({ length: 0, item: () => null, [Symbol.iterator]: [][Symbol.iterator] });
}
if (!Range.prototype.getBoundingClientRect) {
  Range.prototype.getBoundingClientRect = () => ({
    x: 0, y: 0, top: 0, left: 0, right: 0, bottom: 0, width: 0, height: 0, toJSON: () => ({}),
  });
}
