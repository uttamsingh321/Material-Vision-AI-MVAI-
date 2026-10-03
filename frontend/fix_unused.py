import os

base_dir = r"c:\Users\uttam.singh1\Desktop\Material Vision AI (MVAI)\frontend\src"

def replace_in_file(path, old, new):
    full_path = os.path.join(base_dir, path)
    if os.path.exists(full_path):
        with open(full_path, 'r', encoding='utf-8') as f:
            content = f.read()
        content = content.replace(old, new)
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(content)

replace_in_file("contexts/NotificationContext.tsx", "type ReactNode", "")
replace_in_file("contexts/ThemeContext.tsx", "type ReactNode", "")
replace_in_file("pages/UploadPage.tsx", "CheckCircle, AlertCircle", "")
replace_in_file("Providers.tsx", "import type { ReactNode } from 'react';\n", "")

print("Unused imports removed.")
