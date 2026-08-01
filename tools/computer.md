---
name: computer
description: "Operate Windows through UI Automation first. Use windows, activate_window, controls, then invoke/set_value/focus_control. Use coordinate clicks only when controls are unavailable. Native SendInput handles function keys and hotkeys. A blue border shows active control; physical Esc cancels."
parameters:
  action:
    type: string
    required: true
    enum: [screenshot, screen_size, position, windows, activate_window, window_state, controls, inspect_control, read_control, focus_control, invoke, set_value, toggle, select, expand, collapse, scroll_into_view, move, click, double_click, right_click, drag, scroll, type, key, hotkey, key_down, key_up, wait, sequence]
  x: {type: integer, description: "Screen x coordinate"}
  y: {type: integer, description: "Screen y coordinate"}
  to_x: {type: integer, description: "Drag destination x coordinate"}
  to_y: {type: integer, description: "Drag destination y coordinate"}
  text: {type: string, description: "Text to type, key name, window-title query, or control query"}
  window: {type: string, description: "Distinctive window title fragment for UI Automation"}
  handle: {type: integer, description: "Preferred exact window handle returned by windows"}
  control_type: {type: string, description: "Optional UIA type; use text for Edit or Document controls"}
  automation_id: {type: string, description: "Exact UI Automation ID; preferred over fuzzy text"}
  match: {type: string, enum: [contains, exact], description: "Control text matching mode"}
  index: {type: integer, description: "Zero-based index from the current controls result"}
  value: {type: string, description: "Value for set_value or minimize/maximize/restore for window_state"}
  keys: {type: array, items: {type: string}, description: "Hotkey keys, such as [ctrl, s]"}
  amount: {type: integer, description: "Scroll clicks; positive up, negative down"}
  seconds: {type: number, description: "Move/drag duration, typing interval, or wait duration"}
  button: {type: string, enum: [left, middle, right]}
  region: {type: array, items: {type: integer}, description: "Screenshot region [left, top, width, height]"}
  steps: {type: array, items: {type: object}, description: "For sequence, 1-20 ordered deterministic action objects"}
usage_notes:
  - "Start with windows and keep the exact handle. Then call controls with handle plus text/control_type. Prefer invoke for buttons/menu items, set_value for text controls, and focus_control before keyboard input. Use window title only when it is unique."
  - "Use inspect_control/read_control to learn a control's rectangle, enabled/visible state, current value, selection/toggle/expand state, and supported patterns before choosing an action."
  - "Use automation_id with exact matching when available. An index is valid only for the most recent controls result because dynamic interfaces can reorder controls."
  - "Use invoke, toggle, select, expand/collapse, scroll_into_view, set_value, and window_state rather than reproducing those operations with mouse coordinates."
  - "Do not guess coordinates while accessible controls exist. Coordinate click/drag is the last fallback for canvas, remote-desktop, game, or inaccessible custom controls."
  - "Use sequence to combine deterministic UIA/keyboard/wait steps and reduce model round trips. Keep screenshot as verification after an action or sequence."
  - "key/hotkey/key_down/key_up use native Windows SendInput. Supported names include F1-F24, arrows, Home, End, PageUp, PageDown, Insert, Delete, Tab, Enter, Backspace, modifiers, Windows key, media, and volume keys."
  - "Use screenshot to observe the current desktop and verify visually important actions. Repeated screenshots are valid because desktop state changes, but do not use repeated cropped screenshots to hunt for controls."
  - "PyAutoGUI fail-safe is enabled: moving the pointer to the upper-left corner aborts input automation."
  - "Desktop input affects the real user session. Do not perform destructive or irreversible actions without explicit user approval."
  - "A blue border indicates active control. The user can press Esc at any time to cancel; after cancellation, stop and ask what they want to do next."
---

# computer

Use `computer` for visible Windows GUI applications that cannot be handled through files or command-line interfaces. Preferred sequence: inspect windows, activate the target, inspect UI Automation controls, invoke or set the target control, then take one screenshot to verify. Use mouse coordinates only after `controls` shows that the target is inaccessible.
