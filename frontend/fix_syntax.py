import os
import re

base_dir = r"c:\Users\uttam.singh1\Desktop\Material Vision AI (MVAI)\frontend\src\contexts"

for filename in os.listdir(base_dir):
    if filename.endswith(".tsx"):
        path = os.path.join(base_dir, filename)
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        content = content.replace("from 'react' from 'react';", "from 'react';")
        content = content.replace("from 'react' from 'react'", "from 'react';")
        
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)

print("Syntax errors fixed.")
