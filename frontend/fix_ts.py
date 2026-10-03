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

replace_in_file("components/ErrorBoundary.tsx", "import React, { Component, ErrorInfo, ReactNode }", "import { Component, type ErrorInfo, type ReactNode }")
replace_in_file("contexts/AuthContext.tsx", "import React, { createContext, useContext, useState, useEffect }", "import { createContext, useContext, useState } from 'react'")
replace_in_file("contexts/AuthContext.tsx", "export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {", "import type { ReactNode } from 'react';\nexport const AuthProvider: React.FC<{ children: ReactNode }> = ({ children }) => {")
replace_in_file("contexts/WebSocketContext.tsx", "useRef<NodeJS.Timeout>()", "useRef<ReturnType<typeof setTimeout> | undefined>(undefined)")
replace_in_file("contexts/ThemeContext.tsx", "import React, { createContext, useContext, useState, useEffect }", "import { createContext, useContext, useState, useEffect, type ReactNode } from 'react'")
replace_in_file("contexts/NotificationContext.tsx", "import React, { createContext, useContext, useState }", "import { createContext, useContext, useState, type ReactNode } from 'react'")
replace_in_file("Providers.tsx", "import React from 'react';", "import type { ReactNode } from 'react';")
replace_in_file("components/ui/button.tsx", "export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {}", "export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> { variant?: string; }")

print("TypeScript errors fixed.")
