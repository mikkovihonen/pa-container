---
name: design-system-dev
description: Guidelines and conventions for cross-platform W3C DTCG design tokens and component contracts across Web, iOS, and Android
---

# Cross-Platform Design System Development (W3C DTCG & Contracts)

This skill guides autonomous agents (`design_engineer`, `design_steward`, `feature`, `verifier`) in declaring, maintaining, and verifying design system tokens and component contracts across Web, iOS, and Android platforms.

## 1. W3C DTCG Token Specifications (`design/tokens/*.json`)

Design tokens follow the W3C Design Tokens Community Group (DTCG) specification:
- Every token is defined as a JSON object containing `$value` and `$type`.
- Optional `$description` provides designer-to-developer context.
- Grouping paths define canonical token identifiers using dot notation (e.g., `color.brand.primary`).

### 1.1 Token Definition Syntax
```json
{
  "color": {
    "brand": {
      "primary": {
        "$value": "#2563eb",
        "$type": "color",
        "$description": "Primary interactive action color"
      }
    }
  },
  "spacing": {
    "md": {
      "$value": "16px",
      "$type": "dimension"
    }
  }
}
```

### 1.2 Alias Resolution
Tokens can alias primitive values using `{path.to.token}` syntax:
```json
{
  "color": {
    "semantic": {
      "action": {
        "$value": "{color.brand.primary}",
        "$type": "color"
      }
    }
  }
}
```

---

## 2. Multi-Platform Token Consumption

Never hardcode hex colors or raw styling values in component code. Always bind to active design tokens:

### 2.1 Web (Tailwind / CSS Variables)
```css
.btn-primary {
    background-color: var(--color-brand-primary);
    padding: var(--spacing-sm) var(--spacing-md);
}
```

### 2.2 iOS (SwiftUI)
```swift
struct PrimaryButton: View {
    var body: some View {
        Button("Action") {}
            .background(Color.brandPrimary)
            .padding(.horizontal, Spacing.md)
            .accessibilityElement(children: .combine)
    }
}
```

### 2.3 Android (Jetpack Compose)
```kotlin
@Composable
fun PrimaryButton(onClick: () -> Unit) {
    Button(
        onClick = onClick,
        colors = ButtonDefaults.buttonColors(containerColor = DesignTokens.Color.brandPrimary),
        modifier = Modifier.padding(horizontal = DesignTokens.Spacing.md)
    ) {
        Text("Action")
    }
}
```

---

## 3. Component Contracts (`design/contracts/*.toml`)

Each cross-platform component has a formal contract linking platforms, required design tokens, and catalog entries:

```toml
name = "Button"
description = "Core interactive button component"
platforms = ["web", "ios", "android"]
tokens = [
    "color.brand.primary",
    "color.surface.background",
    "spacing.sm",
    "spacing.md"
]

[web]
component = "src/components/Button.tsx"
catalog_entry = "Button.stories.tsx"
a11y_target = "wcag2aa"

[ios]
component = "Sources/DesignSystem/Button.swift"
catalog_entry = "ButtonPreviews.swift"
a11y_target = "accessibilityElement"

[android]
component = "app/src/main/java/com/example/ui/Button.kt"
catalog_entry = "ButtonPreviews.kt"
a11y_target = "contentDescription"
```

---

## 4. Quality Gate Rules (`builtin:design_system`)

The Software Factory automatically evaluates design system compliance before committing or approving code:
1. **Zero Hardcoded Colors:**
    - Any occurrence of raw hex colors (`#RRGGBB` or `#RGB`) in UI components fails the gate.
2. **Contract Token Integrity:**
    - Every token declared in `contract.tokens` must exist in `TokenCatalog`.
3. **Platform Prerequisite Verification:**
    - When `on_missing_platform = "fail"`, every enabled platform in `platforms` must have its required runner toolchain available on host:
        - `web`: Node.js runtime and testing dependencies.
        - `ios`: `xcrun simctl` / Xcode command line tools.
        - `android`: `adb` or Android SDK.
