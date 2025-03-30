// extension.js - Main extension file

const vscode = require('vscode');
const { exec } = require('child_process');
const path = require('path');
const fs = require('fs');

/**
 * @param {vscode.ExtensionContext} context
 */
function activate(context) {
    console.log('AI CLI extension is now active');

    // Register the command for the extension
    let disposable = vscode.commands.registerCommand('clio.executeCommand', async function () {
        // Get user input
        const query = await vscode.window.showInputBox({
            placeHolder: 'Describe what command you need...',
            prompt: 'AI CLI will generate and execute commands for you'
        });

        if (!query) return; // User cancelled

        // Show progress
        vscode.window.withProgress({
            location: vscode.ProgressLocation.Notification,
            title: "AI CLI",
            cancellable: false
        }, async (progress) => {
            progress.report({ message: "Generating commands..." });
            
            try {
                // Path to the clio.py script
                const scriptPath = path.join(context.extensionPath, 'clio.py');
                
                // Execute the script with the query
                const commands = await generateCommands(scriptPath, query);
                
                if (commands.error === "No Command Found") {
                    vscode.window.showInformationMessage("No Command Found");
                    return;
                }
                
                if (commands.error) {
                    vscode.window.showErrorMessage(`Error: ${commands.error}`);
                    return;
                }

                if (!commands.commands || commands.commands.length === 0) {
                    vscode.window.showInformationMessage("No commands generated");
                    return;
                }

                // Show commands to user and ask for confirmation
                const options = commands.commands.map((cmd, index) => ({
                    label: `${index + 1}: ${cmd.command}`,
                    description: cmd.description,
                    detail: `Safety: ${cmd.safety_level}`
                }));

                // Create terminal if it doesn't exist
                let terminal = vscode.window.activeTerminal;
                if (!terminal) {
                    terminal = vscode.window.createTerminal('AI CLI');
                }
                terminal.show();

                // Ask user which commands to execute
                const selectedCommands = await vscode.window.showQuickPick(options, {
                    canPickMany: true,
                    placeHolder: 'Select commands to execute'
                });

                if (!selectedCommands || selectedCommands.length === 0) return;

                // Execute selected commands
                for (const selected of selectedCommands) {
                    const index = parseInt(selected.label.split(':')[0]) - 1;
                    terminal.sendText(commands.commands[index].command);
                }
            } catch (error) {
                vscode.window.showErrorMessage(`Error: ${error.message}`);
            }
        });
    });

    context.subscriptions.push(disposable);

    // Add status bar item
    const statusBarItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
    statusBarItem.text = "$(terminal) AI CLI";
    statusBarItem.tooltip = "Generate and execute CLI commands with AI";
    statusBarItem.command = 'clio.executeCommand';
    statusBarItem.show();
    
    context.subscriptions.push(statusBarItem);
}

// Function to generate commands using clio.py
function generateCommands(scriptPath, query) {
    return new Promise((resolve, reject) => {
        exec(`python "${scriptPath}" "${query}" --json-only`, (error, stdout, stderr) => {
            if (error && error.code !== 1) {
                return reject(error);
            }
            
            try {
                const result = JSON.parse(stdout);
                resolve(result);
            } catch (e) {
                reject(new Error(`Failed to parse response: ${stdout}`));
            }
        });
    });
}

function deactivate() {}

module.exports = {
    activate,
    deactivate
};