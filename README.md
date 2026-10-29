# Voice Assistant for Multimedia Controls (VAMC)

**Team:** Team 15  
**Repository:** [Voice-Assistant-for-Multimedia-Controls-VAMC](https://github.com/SamarthRamesha/Voice-Assistant-for-Multimedia-Controls-VAMC)  
**Requirements baseline:** VAMC SRS v1.0  
**Project status:** Planning and repository setup completed; application implementation pending.

---

## 1. Project Overview

The Voice Assistant for Multimedia Controls (VAMC) is an embedded multimedia-control system designed to let users control media playback using **voice commands and optional hand gestures**.

The system is intended to capture voice input, convert speech to text, identify the user's intended command, and perform the corresponding action on a connected media player. Gesture recognition provides an alternative way to control volume and playback.

The broader project also includes user feedback, device configuration, a web dashboard, logging, performance monitoring, and security controls.

### Project objectives

- Control multimedia playback without repeatedly interacting with a keyboard, mouse, or remote.
- Support voice-based volume and playback commands.
- Provide an alternative gesture-based control mode.
- Give users feedback when commands are processed or fail.
- Provide a dashboard for monitoring and configuring the system.
- Meet the functional, performance, reliability, and security requirements defined in the SRS.

## 2. Current Project Status

The following work has been completed:

- [x] Created the GitHub repository.
- [x] Created and organized the GitHub Issues backlog for the 30 SRS requirements.
- [x] Added requirement IDs, requirement types, and story-point estimates to the issues.
- [x] Assigned issues among the four team members.
- [x] Created the initial GitHub Actions workflow at `.github/workflows/main.yml`.
- [x] Committed the workflow to the `main` branch.
- [x] Verified that the initial GitHub Actions run passed.

### What is not implemented yet

The repository now contains a portable Python core, mock media and hardware-facing adapters, and automated tests. Real microphone, GPIO, LED and media-player validation still requires the target hardware and operating-system integrations.

The GitHub Actions workflow checks the README, installs Python dependencies and runs the automated test suite. Hardware-dependent acceptance tests must still be run separately on the target device.

### Running the implementation

Create an isolated environment and run the automated tests:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
PYTHONPATH=src .venv/bin/python -m pytest -q
```

Run the safe mock demo:

```bash
PYTHONPATH=src .venv/bin/python -m vamc
```

On Linux, `--real` uses `amixer` for volume/mute operations and `playerctl` for
playback. Install those system tools and configure the target mixer/player before
using it:

```bash
PYTHONPATH=src .venv/bin/python -m vamc --real
```

The real mode does not claim hardware acceptance by itself. Hardware validation and
the NF-001/NF-002/NF-003 performance, accuracy and reliability measurements remain
separate acceptance activities.

## 3. Project Requirements

The VAMC SRS v1.0 defines 30 requirements.

| Requirement category | IDs | Scope |
|---|---|---|
| Functional | F-001 to F-020 | Voice, gestures, playback, feedback, dashboard, configuration and logging |
| Non-functional | NF-001 to NF-005 | Latency, recognition accuracy, reliability, responsiveness and log retention |
| Security | SR-001 to SR-005 | Authentication, secure communication, credential protection, signed updates and login lockout |

The SRS and its acceptance criteria are the authoritative specification. GitHub Issues should be used to track implementation, discussion, testing and completion.

## 4. Sprint 1 Scope

The team has agreed that GitHub issues **#1 through #15** are Sprint 1 and
issues **#16 through #30** are Sprint 2. Sprint 1 therefore covers the initial
voice, volume, playback and gesture requirements through F-015. Feedback,
dashboard, logging and security work beginning with F-016 is Sprint 2.

## 5. Suggested Technical Direction

The SRS describes a Python-based control application running on a Raspberry Pi or an appropriate ESP32-based arrangement. The final implementation must account for the hardware and available libraries.

The following technologies are suggested by the existing project specification. They are not all installed or implemented in the repository yet.

| Component | Candidate technology or approach |
|---|---|
| Main control application | Python |
| Speech recognition | Vosk or Google Speech API |
| Gesture recognition for later work | MediaPipe Hands |
| Dashboard for later work | Flask or FastAPI, with WebSocket support if needed |
| Local configuration and logs | SQLite or JSON |
| Hardware interface | Raspberry Pi GPIO or the appropriate ESP32 interface |
| Testing | pytest; suitable integration and system tests |
| Version control and CI | GitHub, GitHub Issues, Pull Requests and GitHub Actions |

### Important implementation rule

Choose the simplest architecture that meets the SRS and the hardware available to the team. Do not introduce a database, cloud service, complex framework, or paid API merely because an AI assistant recommends it.

Before committing to a technology, confirm that it can run on the team's actual hardware and operating system. If a required peripheral is unavailable, implement a testable abstraction or mock where appropriate, document the limitation, and do not claim that physical hardware testing has passed.

## 6. Sprint 1 Implementation Plan

### Phase A: Establish the application foundation

1. Review the SRS, Software Architecture Design (SAD), Test Plan and relevant GitHub Issues.
2. Confirm the target hardware, operating system, Python version and available microphone, GPIO button, media player and LED.
3. Agree on a common application structure, dependency-management approach and configuration format.
4. Create a minimal runnable application with a clear entry point.
5. Separate voice capture, speech recognition, intent mapping, multimedia actions and feedback into testable modules.
6. Provide a mock media controller and mock hardware interfaces so the core logic can be tested without every peripheral connected.
7. Add setup instructions and dependency installation steps.

Do not begin by building every feature in one large script. Create small, understandable modules with clear interfaces so different teammates can work in parallel.

### Phase B: Implement voice input

Implement F-001 through F-004 as assigned in the approved sprint plan.

- **F-001, wake-word listening:** listen for a configurable wake word and enter command-listening mode when detected.
- **F-002, speech-to-text:** convert captured speech into text using the selected ASR engine.
- **F-003, intent mapping:** map recognised phrases to supported command intents rather than executing arbitrary recognised text.
- **F-004, push-to-talk:** support a physical GPIO button as an alternative to wake-word activation.

Acceptance criteria explicitly stated in the SRS include:

- F-001: saying the wake word activates listening within 1 second.
- F-002: achieve at least 90% word accuracy in a quiet room.
- F-003: correctly select the intended command for the six supported command phrases.
- F-004: pressing the GPIO button starts listening without requiring the wake word.

Consult the full SRS and the individual GitHub Issues for the remaining acceptance criteria, dependencies and test references. Do not invent a replacement specification.

### Phase C: Implement multimedia actions

Implement the volume and playback requirements assigned to Sprint 1.

- **F-006:** increase volume.
- **F-007:** decrease volume.
- **F-008:** mute and unmute, restoring the previous volume after unmuting.
- **F-009:** play media.
- **F-010:** pause media.

The intent-mapping module must invoke the appropriate action through a defined media-control interface. Keep command recognition separate from the implementation that actually changes volume or playback.

Use the appropriate native media-control API or a suitable player integration for the target operating system. If a real player integration is not available during development, use a mock controller for unit tests and clearly identify which tests still require integration with a real player.

### Phase D: Verify the Sprint 1 non-functional requirements

**NF-001: Command latency**

Measure the time from command activation or capture to completion of the requested action, using the measurement boundaries defined in the SRS. Collect multiple samples and calculate the 90th percentile. The target is no more than 2 seconds.

**NF-002: Recognition accuracy**

Prepare a labelled set of test utterances for the supported commands. Record the expected transcript or intent and the observed result. Evaluate accuracy in a quiet room and document the test sample size and calculation method. The target is at least 90%.

**NF-003: Reliability**

Plan an eight-hour continuous-operation soak test. Record crashes, unhandled exceptions, restarts and relevant resource or log information. A short unit test or successful application launch does not prove this requirement has passed.

Feedback and dashboard authentication are Sprint 2 work under the team’s
issue-number split and must not be claimed as Sprint 1 acceptance.

## 7. Testing Requirements

Every implemented feature must have tests tied to its requirement ID.

### Minimum testing expectations

1. **Unit tests:** test command mapping, volume calculations, mute/restore behaviour, playback action selection and error handling.
2. **Integration tests:** test the connection between recognised commands and the media-control interface.
3. **Hardware tests:** verify GPIO, microphone, audio output and LED behaviour when the relevant hardware is available.
4. **Performance tests:** collect measurements for NF-001 and NF-002 using documented test procedures.
5. **Reliability test:** execute the NF-003 soak test for the required duration.
6. **Security tests:** verify that unauthenticated configuration changes are rejected wherever SR-001 applies.
7. **Regression tests:** rerun the relevant tests whenever code is changed.

Use pytest for Python unit tests where suitable. Tests should be repeatable and should not require a live microphone, physical GPIO pin or external media service unless they are explicitly integration or hardware tests.

### Test evidence

For each requirement, record:

- Requirement ID and GitHub Issue number.
- Test case ID.
- Test setup and input.
- Expected result.
- Actual result.
- Pass/fail status.
- Evidence or logs.
- Any defect, limitation or outstanding dependency.

Do not mark a test as passed just because the code exists. Do not fabricate performance numbers, hardware test results or screenshots.

## 8. GitHub Collaboration Workflow

The repository is shared by the following team members:

- Samarth Ramesha
- Samanvith Kashyap
- Ruhika Kolla
- Saketh Sunil Pai (`SavvyHex` on GitHub)

Follow this workflow for each implementation task.

1. Open the assigned GitHub Issue and read its description, acceptance criteria and dependencies.
2. Create a feature branch from the latest `main` branch. Use a descriptive name, such as `feature/f-001-wake-word`.
3. Implement only the assigned, agreed scope. Coordinate shared interfaces with teammates before changing them.
4. Add or update tests alongside the implementation.
5. Run the relevant tests locally and record any known limitations.
6. Commit changes with a meaningful message, such as `feat: implement wake-word detection`.
7. Push the feature branch and open a Pull Request against `main`.
8. Reference the relevant issue in the PR description, for example `Closes #1`, after verifying the actual issue number.
9. Explain what changed, how it was tested, and what remains incomplete.
10. Wait for review and required checks. Resolve feedback before merging.

Do not guess issue numbers. Do not commit API keys, passwords, Wi-Fi credentials, access tokens or other secrets. Avoid committing generated files, local environment files or large audio recordings unless the team has explicitly agreed that they belong in the repository.

The repository currently has an initial GitHub Actions workflow. Once application code and tests exist, update CI to install the correct dependencies and run the actual automated checks. Do not treat the existing README check as a substitute for application tests.

## 9. Definition of Done for a Sprint 1 Issue

A requirement is complete only when all applicable conditions below are satisfied:

- [ ] The implementation matches the SRS and issue acceptance criteria.
- [ ] The code follows the agreed module interfaces and coding conventions.
- [ ] Appropriate automated tests have been added or updated.
- [ ] Relevant tests have been executed and their results recorded.
- [ ] Hardware-dependent validation has been completed or explicitly documented as outstanding.
- [ ] Known limitations and dependencies have been documented.
- [ ] The feature branch has been pushed and a Pull Request opened.
- [ ] The Pull Request has been reviewed and required checks have passed.
- [ ] The change has been merged according to the team's agreed process.
- [ ] The GitHub Issue and project status reflect the actual state of the work.

A partially working feature must remain marked as incomplete if it fails an acceptance criterion.

## 10. Documentation and Sprint Deliverables

Keep the repository understandable to another developer who has never seen the project.

Recommended documentation structure:

```text
.
├── README.md
├── .github/
│   └── workflows/
│       └── main.yml
├── docs/
│   ├── SRS.pdf
│   ├── SAD.pdf
│   ├── TEST_PLAN.pdf
│   └── test-results/
├── src/
├── tests/
├── requirements.txt
└── .gitignore
```

This is a suggested structure, not a description of files that already exist. Adapt it to the final implementation and avoid maintaining duplicate or conflicting copies of the same document.

Before Sprint 1 review, prepare the deliverables requested by the instructor, including:

- A working, demonstrable subset of the VAMC application.
- Source code and relevant automated tests.
- Test results mapped to the Sprint 1 requirements.
- Updated documentation and known limitations.
- A clear demonstration of the implemented product.

The instructor has specified a **one-minute Sprint 1 working-product demo** and a **two-minute Sprint 2 working-product demo**. Confirm the required submission format and other review instructions with the team.

## 11. Instructions for AI Coding Assistants

Any AI assistant helping with this repository must follow these rules.

1. Treat this README, the SRS v1.0, the SAD, the Test Plan and the actual GitHub Issue acceptance criteria as the project's specification.
2. Inspect the existing repository and files before suggesting edits. Do not assume the application already exists.
3. Confirm the actual Sprint 1 scope from GitHub Projects before starting work.
4. Ask for missing hardware, operating-system or API details when they materially affect implementation. Otherwise, use a small, testable abstraction and state the assumption.
5. Prefer a simple, modular implementation that can run on the team's target hardware.
6. Never claim to have executed commands, tests, hardware checks or GitHub actions unless they were actually executed.
7. Never invent passing results, requirement acceptance, issue numbers, API credentials or installed dependencies.
8. Preserve working code and existing interfaces unless a change is necessary and explained.
9. Include complete code for the requested change, file paths, installation steps, run commands and relevant tests.
10. Explain commands one at a time when guiding a teammate who is setting up the project locally.
11. Do not implement all 30 requirements as one giant change. Work on the assigned Sprint 1 issue, test it, and integrate it through a Pull Request.
12. When a requirement depends on physical hardware, distinguish between mocked tests and actual hardware validation.
13. When finishing a task, summarize files changed, tests executed, results, known limitations and the next concrete step.

### Starter prompt for an AI assistant

Copy and paste this prompt along with the relevant GitHub Issue and, where possible, the SRS:

> I am working on Team 15's Voice Assistant for Multimedia Controls (VAMC) project. Read this README and the supplied SRS, SAD, Test Plan and assigned GitHub Issue carefully.
>
> First inspect the existing codebase and explain what already exists. Confirm that the issue belongs to the approved Sprint 1 scope. Do not assume files, hardware, dependencies or implementations exist when they have not been verified.
>
> Help me implement **only the assigned requirement** in a modular, testable way. Follow its acceptance criteria exactly. Identify dependencies, propose the smallest suitable design, show the files to create or modify, provide the implementation and tests, and explain how to install, run and validate it.
>
> Use mocks for unavailable hardware or external services where appropriate, but clearly distinguish mocked tests from real hardware or integration tests. Do not fabricate test results. Preserve the team's existing interfaces and coordinate any changes that affect other modules.
>
> Finally, provide a checklist for verifying the requirement, the exact local test commands, any remaining limitations, and a suggested commit message and Pull Request description. Do not claim the issue is complete until its acceptance criteria have actually been verified.

## 12. Final Project Principle

**The goal is a working and verifiable multimedia-control system, not simply a repository full of code.**

Every implementation should map to a requirement, every requirement should have an appropriate verification method, and every claim of completion should be backed by evidence. Keep the design small, the interfaces clear, the tests repeatable and the Git history reviewable.
