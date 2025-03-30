#!/usr/bin/env python3
import os
import json
import subprocess
import requests
import re
import sys
import tempfile

# API configuration
API_KEY = os.environ.get("OPENROUTER_API_KEY", "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")
API_URL = "https://openrouter.ai/api/v1/chat/completions"

# Tool detection weights
TOOL_WEIGHTS = {
    "git": {
        "keywords": {
            "git": 120, "commit": 100, "branch": 100, "push": 100, "pull": 100,
            "merge": 100, "clone": 100, "repository": 90, "repo": 90, 
            "checkout": 90, "main": 80, "master": 80, "origin": 80,
            "staged": 80, "status": 70, "log": 60, "diff": 60, "fetch": 60
        },
        "context_clues": [".git", "git"]
    },
    "docker": {
        "keywords": {
            "docker": 120, "container": 110, "image": 100, "volume": 100,
            "compose": 100, "dockerfile": 100, "registry": 90, "hub": 80,
            "build": 70, "pull": 70, "push": 70, "run": 70, "exec": 70,
            "stop": 70, "start": 70, "restart": 70, "remove": 70, "ps": 70
        },
        "context_clues": ["docker", "Dockerfile", "docker-compose.yml"]
    },
    "nodejs": {
        "keywords": {
            "node": 120, "npm": 120, "yarn": 120, "javascript": 100, "js": 110,
            "package.json": 110, "package": 70, "module": 70, "server.js": 110,
            "express": 90, "react": 80, "vue": 80, "angular": 80, "next": 80,
            "start": 60, "install": 70, "dependency": 70, "dev": 60
        },
        "context_clues": ["package.json", "node_modules", ".js", ".ts", ".jsx", ".tsx"]
    },
    "linux": {
        "keywords": {
            "ls": 70, "cd": 70, "mv": 70, "cp": 70, "rm": 70, "mkdir": 70,
            "touch": 70, "chmod": 70, "chown": 70, "grep": 70, "find": 70,
            "cat": 70, "echo": 70, "sudo": 70, "apt": 70, "yum": 70, "dnf": 70,
            "bash": 80, "shell": 80, "terminal": 80, "command": 60, "linux": 80,
            "file": 60, "directory": 60, "folder": 60, "permission": 60
        },
        "context_clues": ["/etc", "/var", "/home", "/usr", "/bin"]
    },
    "windows": {
        "keywords": {
            "cmd": 90, "powershell": 90, "batch": 80, "dir": 80, "del": 80,
            "copy": 70, "move": 70, "ren": 70, "type": 70, "findstr": 70,
            "windows": 90, "exe": 70, "bat": 70, "taskkill": 80, "tasklist": 80,
            "reg": 80, "netsh": 80, "sfc": 80, "dism": 80, "wmic": 80
        },
        "context_clues": [".exe", ".bat", ".ps1", "C:\\", "Windows"]
    }
}

# Safety patterns
SAFETY_PATTERNS = {
    "dangerous": [
        r"rm\s+-rf", r"rm\s+.*-f", r"rm\s+.*--force",
        r"dd\s+if=.*of=.*", r":(){.*};:",
        r"chmod\s+777", r"chmod\s+.*a=rwx",
        r"sudo\s+.*rm", r"sudo\s+rm",
        r"mv\s+.*\s+/dev/null",
        r">\s+/dev/sda", r"mkfs", r"fdisk",
        r"DROP\s+.*DATABASE", r"DROP\s+.*TABLE",
        r"FORMAT", r"del\s+.*\s+/s\s+/q",
        r"rd\s+.*\s+/s\s+/q", r"taskkill\s+.*\s+/f",
    ],
    "moderate_risk": [
        r"git\s+push", r"git\s+merge", r"git\s+rebase",
        r"docker\s+stop", r"docker\s+rm", r"docker\s+kill",
        r"docker\s+system\s+prune", r"npm\s+install\s+.*--global",
        r"pip\s+install", r"apt\s+.*remove", r"apt\s+.*purge",
        r"yum\s+.*remove", r"dnf\s+.*remove", r"mv\s+.*\s+.*",
        r"shutdown", r"reboot", r"systemctl\s+.*stop",
        r"systemctl\s+.*restart", r"kill", r"pkill"
    ],
    "low_risk": [
        r"git\s+commit", r"git\s+add", r"git\s+pull",
        r"docker\s+build", r"docker\s+pull", r"docker\s+run",
        r"npm\s+install\s+.*--save", r"npm\s+install\s+.*--save-dev",
        r"touch", r"mkdir", r"rmdir", r"cat\s+.*\s+>",
        r">\s+.*\.txt", r">\s+.*\.log",
    ]
}

# Check if query is a general conversation rather than a command request
GENERAL_QUERY_PATTERNS = [
    r"(?:how|what)\s+are\s+you",
    r"(?:who|what)\s+(?:are|is)\s+(?:you|this)",
    r"hello|hi|hey|greetings",
    r"(?:can|could)\s+you\s+(?:help|assist)",
    r"(?:tell|talk)\s+(?:me|us)\s+about\s+(?:yourself|you)",
    r"(?:what|how)\s+(?:do|can|could)\s+you\s+do",
    r"thanks|thank\s+you",
    r"bye|goodbye"
]

def is_general_query(query):
    """Check if the query is general conversation rather than a command request"""
    query_lower = query.lower()
    for pattern in GENERAL_QUERY_PATTERNS:
        if re.search(pattern, query_lower):
            return True
    return False

def detect_tool(query, current_directory="."):
    """Detect the most likely tool based on query and context"""
    scores = {tool: 0 for tool in TOOL_WEIGHTS}
    
    # Score based on keywords in query
    for tool, data in TOOL_WEIGHTS.items():
        for keyword, weight in data["keywords"].items():
            # Use word boundary for more precise matching
            if re.search(r'\b' + re.escape(keyword.lower()) + r'\b', query.lower()):
                scores[tool] += weight
    
    # Add context clues from current directory
    try:
        items = os.listdir(current_directory)
        for tool, data in TOOL_WEIGHTS.items():
            for clue in data["context_clues"]:
                for item in items:
                    if clue in item:
                        # Context clues have lower weight to prevent overriding strong query intent
                        scores[tool] += 15
                        break
    except Exception as e:
        # More specific error handling
        pass  # If directory can't be read, just ignore context
    
    # Special case adjustments based on specific patterns
    # Higher priority for Node.js with .js files in query
    if re.search(r'\b[\w-]+\.js\b', query.lower()):
        scores["nodejs"] += 50
    
    # Docker with container or image listing
    if re.search(r'\b(list|show|display).*container', query.lower()):
        scores["docker"] += 60
    
    # Get the tool with highest score
    best_tool = max(scores.items(), key=lambda x: x[1])
    
    # Return None if no significant match
    if best_tool[1] < 40:
        return None
    
    return best_tool[0]

def check_safety(command):
    """Check command safety and return appropriate safety level and confirmation requirement"""
    if not command or not isinstance(command, str):
        return "safe", False
        
    command_lower = command.lower()
    
    for pattern in SAFETY_PATTERNS["dangerous"]:
        if re.search(pattern, command_lower):
            return "dangerous", True
            
    for pattern in SAFETY_PATTERNS["moderate_risk"]:
        if re.search(pattern, command_lower):
            return "moderate_risk", True
            
    for pattern in SAFETY_PATTERNS["low_risk"]:
        if re.search(pattern, command_lower):
            return "low_risk", False
            
    return "safe", False

def get_platform():
    """Detect the user's operating system"""
    if sys.platform.startswith('win'):
        return "windows"
    elif sys.platform.startswith(('linux', 'darwin', 'freebsd')):
        return "linux"
    else:
        return "linux"  # Default to Linux/Unix-like

def generate_cli_commands(query):
    """Generate multiple CLI commands (up to 5) using AI model"""
    if not query or not isinstance(query, str) or query.strip() == "":
        return {"error": "Empty query", "commands": []}
        
    if is_general_query(query):
        return {"error": "No Command Found", "commands": []}
    
    if not API_KEY:
        return {"error": "API key not found. Please set OPENROUTER_API_KEY environment variable."}
    
    detected_tool = detect_tool(query)
    platform = get_platform()
    
    # Build a prompt that guides the model
    system_prompt = f"""You are an expert CLI assistant that generates precise, executable commands based on user requests.
For the query, respond ONLY with a JSON object containing:
- 'commands': an array of 1-5 command objects, each containing:
  - 'command': the exact command to run
  - 'description': a brief explanation of what the command does
  - 'safety_level': one of ['safe', 'low_risk', 'moderate_risk', 'dangerous']
  - 'confirm_required': true or false (whether user should confirm before execution)

Only generate multiple commands (up to 5 maximum) if the task requires sequential steps. 
If the task can be done with one command, return just one command object in the array.

The detected tool is {detected_tool or "unknown"} and the platform is {platform}.

Safety guidelines:
- 'dangerous': Commands that could lose data or harm the system (rm -rf, chmod 777)
- 'moderate_risk': Commands that modify state but are generally recoverable (git push, docker stop)
- 'low_risk': Commands that make minor changes (git commit, mkdir)
- 'safe': Commands that only read or display information (ls, git status)

Commands that delete, overwrite, or significantly modify data should be 'moderate_risk' or 'dangerous' and require confirmation.

Use idiomatic commands for the detected tool and platform. For Windows, use appropriate commands (dir instead of ls, etc.).

IMPORTANT: Output ONLY valid JSON without any other text, explanation, or markdown formatting.
Do not generate commands for general conversation or non-command queries.
"""

    examples = [
        {"role": "user", "content": "push my code"},
        {"role": "assistant", "content": '{"commands": [{"command": "git push origin main", "description": "Pushes committed code changes to the main branch on the remote repository", "safety_level": "moderate_risk", "confirm_required": true}]}'},
        {"role": "user", "content": "create a new folder called project and initialize a git repo inside it"},
        {"role": "assistant", "content": '{"commands": [{"command": "mkdir project", "description": "Creates a new directory named project", "safety_level": "low_risk", "confirm_required": false}, {"command": "cd project", "description": "Changes directory to the newly created project folder", "safety_level": "safe", "confirm_required": false}, {"command": "git init", "description": "Initializes a new Git repository", "safety_level": "low_risk", "confirm_required": false}]}'},
        {"role": "user", "content": "how are you doing today?"},
        {"role": "assistant", "content": '{"error": "No Command Found", "commands": []}'}
    ]
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}"
    }
    
    data = {
        "model": "deepseek/deepseek-chat",
        "messages": [
            {"role": "system", "content": system_prompt},
            *examples,
            {"role": "user", "content": query}
        ],
        "max_tokens": 400,
        "temperature": 0.1
    }
    
    try:
        response = requests.post(API_URL, headers=headers, json=data, timeout=30)
        response.raise_for_status()
        response_data = response.json()
        
        # Extract the AI's response
        ai_response = response_data["choices"][0]["message"]["content"].strip()
        
        # Clean the response to ensure it's valid JSON
        # Remove markdown code blocks if present
        ai_response = re.sub(r'```json\s*|\s*```', '', ai_response)
        
        # Clean any non-JSON text before or after
        ai_response = re.search(r'({.*})', ai_response, re.DOTALL)
        if ai_response:
            ai_response = ai_response.group(1)
        else:
            return {"error": "Invalid response format from API", "commands": []}
        
        try:
            response_json = json.loads(ai_response)
        except json.JSONDecodeError:
            return {"error": "Failed to parse JSON response", "commands": []}
        
        # Check if response has an error field
        if "error" in response_json:
            return response_json
        
        # Make sure "commands" field exists
        if "commands" not in response_json:
            return {"error": "No commands found in response", "commands": []}
            
        # Verify commands is a list/array
        if not isinstance(response_json["commands"], list):
            return {"error": "Commands field is not an array", "commands": []}
        
        # Verify safety level for each command
        for i, cmd_data in enumerate(response_json["commands"]):
            # Skip if command is missing
            if "command" not in cmd_data:
                continue
                
            # Check if all required fields exist
            for field in ["description", "safety_level", "confirm_required"]:
                if field not in cmd_data:
                    cmd_data[field] = "Unknown" if field != "confirm_required" else True
            
            # Validate command content
            if not cmd_data["command"] or not isinstance(cmd_data["command"], str):
                continue
                
            safety_level, confirm_required = check_safety(cmd_data["command"])
            
            # Override model's safety classification if our check is more cautious
            safety_levels = ["safe", "low_risk", "moderate_risk", "dangerous"]
            model_safety_idx = safety_levels.index(cmd_data["safety_level"]) if cmd_data["safety_level"] in safety_levels else 0
            our_safety_idx = safety_levels.index(safety_level)
            
            if our_safety_idx > model_safety_idx:
                response_json["commands"][i]["safety_level"] = safety_level
                response_json["commands"][i]["confirm_required"] = confirm_required
        
        # Filter out invalid commands
        response_json["commands"] = [cmd for cmd in response_json["commands"] 
                                    if "command" in cmd and cmd["command"] and isinstance(cmd["command"], str)]
        
        return response_json
        
    except requests.exceptions.RequestException as e:
        return {"error": f"API request failed: {str(e)}", "commands": []}
    except Exception as e:
        return {"error": f"Unexpected error: {str(e)}", "commands": []}

def format_safety_level(level):
    """Convert safety level to user-friendly text"""
    if level == "safe":
        return "Safe - Read-only command"
    elif level == "low_risk":
        return "Low Risk - Minor system changes"
    elif level == "moderate_risk":
        return "Caution - System modifications"
    elif level == "dangerous":
        return "Warning - Potentially destructive"
    else:
        return "Unknown risk level"

def display_friendly_output(command_data):
    """Display command information in a user-friendly format"""
    if "error" in command_data and command_data["error"]:
        if command_data["error"] == "No Command Found":
            print("No Command Found")
        else:
            print(f"Error: {command_data['error']}")
        return False
    
    if not command_data.get("commands"):
        print("No commands to execute.")
        return False
    
    for i, cmd in enumerate(command_data['commands']):
        if not cmd.get("command"):
            continue
        print(f"Command : {cmd['command']}")
        print(f"Description: {cmd.get('description', 'No description provided')}")
        print(f"Risk Level: {format_safety_level(cmd.get('safety_level', 'unknown'))}")
        print("")
    
    return True

def execute_commands(command_data):
    """Execute the generated commands with correct directory persistence"""
    if "error" in command_data and command_data["error"]:
        print(f"Error: {command_data['error']}")
        return
    
    if not command_data.get("commands"):
        print("No commands to execute.")
        return
    
    # Ask for confirmation if any commands require it
    any_confirm_required = any(cmd.get("confirm_required", False) for cmd in command_data['commands'])
    if any_confirm_required:
        print("\nNote: Some commands carry risk and require confirmation.")
    
    # Platform-specific execution
    if sys.platform.startswith('win'):
        # Create a batch file with all commands
        batch_commands = ["@echo off"]
        for cmd in command_data['commands']:
            if not cmd.get("command"):
                continue
            batch_commands.append(f"echo Executing: {cmd['command']}")
            batch_commands.append(cmd['command'])
            batch_commands.append("if %errorlevel% neq 0 (")
            batch_commands.append("  echo Command failed with error %errorlevel%")
            batch_commands.append("  pause")
            batch_commands.append("  exit /b %errorlevel%")
            batch_commands.append(")")
        
        # Write to a temporary batch file
        try:
            with tempfile.NamedTemporaryFile(suffix='.bat', delete=False, mode='w') as f:
                temp_batch = f.name
                f.write("\n".join(batch_commands))
            
            # Execute the batch file
            subprocess.run(temp_batch, shell=True, check=False)
            print("Commands execution completed.")
        except Exception as e:
            print(f"Error during execution: {e}")
        finally:
            # Clean up the temporary file
            try:
                os.remove(temp_batch)
            except:
                pass
    else:
        # For Unix-like systems, execute commands sequentially
        for i, cmd in enumerate(command_data['commands']):
            if not cmd.get("command"):
                continue
                
            print(f"\nExecuting: {cmd['command']}")
            try:
                result = subprocess.run(cmd['command'], shell=True, capture_output=True, text=True)
                
                # Print command output
                if result.stdout:
                    print(result.stdout)
                
                if result.returncode != 0:
                    print(f"Command failed with error code {result.returncode}")
                    if result.stderr:
                        print(f"Error details: {result.stderr}")
                    
                    should_continue = input("Continue with remaining commands? (Y/N): ")
                    if should_continue.lower() != 'y':
                        print("Execution stopped.")
                        break
                else:
                    print("Command executed successfully.")
            except Exception as e:
                print(f"Error executing command: {e}")
                should_continue = input("Continue with remaining commands? (Y/N): ")
                if should_continue.lower() != 'y':
                    print("Execution stopped.")
                    break

def main():
    # Check if --json-only flag is present (for VS Code extension)
    json_only = "--json-only" in sys.argv
    if json_only and "--json-only" in sys.argv:
        # Remove the flag from arguments
        sys.argv.remove("--json-only")
        
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
        result = generate_cli_commands(query)
        
        if json_only:
            # Return only JSON output for programmatic usage
            print(json.dumps(result))
            return
        
        # Display user-friendly output instead of raw JSON
        has_commands = display_friendly_output(result)
        
        # Ask for execution only if we have valid commands
        if has_commands:
            execute = input("Execute these commands? (Y/N): ")
            if execute.lower() == 'y':
                execute_commands(result)
    else:
        # If no arguments, prompt for input
        query = input("Enter your command in natural language: ")
        result = generate_cli_commands(query)
        
        # Display user-friendly output instead of raw JSON
        has_commands = display_friendly_output(result)
        
        # Ask for execution only if we have valid commands
        if has_commands:
            execute = input("Execute these commands? (Y/N): ")
            if execute.lower() == 'y':
                execute_commands(result)

if __name__ == "__main__":
    main()