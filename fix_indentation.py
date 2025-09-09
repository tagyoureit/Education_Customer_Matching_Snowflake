#!/usr/bin/env python3
"""
Script to fix indentation issues in app.py after adding tabs
"""

def fix_app_indentation():
    # Read the file
    with open('app.py', 'r') as f:
        lines = f.readlines()
    
    # Find the critical section boundaries
    tab_data_start = None
    tab_chat_start = None
    form_start = None
    
    for i, line in enumerate(lines):
        if 'with tab_data:' in line:
            tab_data_start = i
        elif 'with tab_chat:' in line:
            tab_chat_start = i
            break
        elif tab_data_start and 'with st.form(' in line:
            form_start = i
    
    print(f"tab_data: {tab_data_start + 1}, form: {form_start + 1}, tab_chat: {tab_chat_start + 1}")
    
    # Fix indentation issues
    fixed_lines = []
    
    for i, line in enumerate(lines):
        # If we're in the form block area, check indentation
        if form_start and i > form_start and i < tab_chat_start:
            stripped = line.lstrip()
            if stripped:  # Non-empty line
                current_indent = len(line) - len(stripped)
                
                # Determine correct indentation based on content
                if stripped.startswith('def '):
                    # Function definition inside form - should be 20 spaces
                    target_indent = 20
                elif any(stripped.startswith(x) for x in ['"""', 'details_parts', 'if ', 'return']):
                    # Function body content - should be 24 spaces  
                    target_indent = 24
                elif stripped.startswith('# '):
                    # Comments - should be 16 spaces (form content level)
                    target_indent = 16
                elif any(stripped.startswith(x) for x in ['col', 'with col', 'name = ', 'source_system', 'address', 'city', 'state', 'postal', 'country']):
                    # Form elements - should be 16 spaces
                    target_indent = 16
                elif stripped.startswith('if ') and ('submitted' in stripped or 'new_record' in stripped):
                    # Form submission logic - should be 16 spaces
                    target_indent = 16
                elif any(stripped.startswith(x) for x in ['elif ', 'else:', 'record_data', 'success', 'new_id']):
                    # Inside form submission logic - should be 20 spaces
                    target_indent = 20
                elif stripped.startswith('st.'):
                    # Streamlit calls - context dependent
                    if 'st.form_submit_button' in stripped or 'st.text_input' in stripped:
                        target_indent = 20  # Inside form elements
                    else:
                        target_indent = 24  # Inside conditional blocks
                else:
                    # Default: keep current indentation if reasonable
                    target_indent = max(16, current_indent)
                
                # Apply the fix
                if current_indent != target_indent:
                    new_line = ' ' * target_indent + stripped
                    fixed_lines.append(new_line)
                    if i < 1150:  # Only print first few for debugging
                        print(f"Line {i+1}: {current_indent} -> {target_indent}: {stripped[:50]}")
                else:
                    fixed_lines.append(line)
            else:
                fixed_lines.append(line)
        else:
            fixed_lines.append(line)
    
    # Write the fixed file
    with open('app.py', 'w') as f:
        f.writelines(fixed_lines)
    
    print("Indentation fixes applied!")

if __name__ == "__main__":
    fix_app_indentation()