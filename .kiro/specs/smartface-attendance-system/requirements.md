# Requirements Document

## Introduction

SmartFace is a real-time face recognition attendance monitoring system developed for St. Anne College Lucena, Inc. (SACLI). The system allows Faculty/Staff to operate a kiosk that automatically identifies students via webcam, records attendance, and supports Administrators with enrollment management, reporting, and audit oversight. Students may view their own attendance records. The system is built as a Flask web application with a dlib-based facial recognition pipeline, a MySQL database, and Jinja2-rendered templates — deployed on localhost for demo and LAN for institutional use.

---

## Glossary

- **SmartFace**: The face recognition attendance monitoring system being specified.
- **SACLI**: St. Anne College Lucena, Inc. — the institution deploying SmartFace.
- **Administrator**: A user with full access to all SmartFace features, including enrollment, user management, reports, manual overrides, and audit logs.
- **Faculty/Staff**: A user who may operate the kiosk, view the dashboard, and generate attendance reports, but cannot manage users or view audit logs.
- **Student**: A user who may only view their own attendance records via `/my-attendance`.
- **Kiosk**: The live recognition screen (`/kiosk`) where the webcam feed is displayed and attendance is logged in real time.
- **Facial Encoding**: A 128-dimensional float64 vector produced by the `face_recognition` library representing a person's face.
- **Face Matching**: The process of comparing an unknown facial encoding against the in-memory cache of known facial encodings using Euclidean distance.
- **Enrollment**: The process of capturing 3–5 face samples from a user, computing facial encodings, and persisting them to the database.
- **Debounce**: A rule that prevents redundant attendance updates: the first recognition of the day triggers an `INSERT` with `time_in`; subsequent recognitions trigger an `UPDATE` to `time_out` only if 60 or more seconds have elapsed since the last update.
- **TOLERANCE**: The maximum acceptable Euclidean face distance for a positive face match, set to `0.45` by default.
- **LATE_TIME**: The threshold time after which a `time_in` is recorded with `status = 'late'`, set to `08:00:00` by default.
- **Encoding_Cache**: The module-level in-memory Python list of all known facial encodings, loaded at application startup and refreshed after each enrollment.
- **Last_Seen_Dict**: The module-level in-memory Python dictionary mapping `user_id` to the timestamp of the most recent frame in which that user was recognized, used as the primary debounce guard.
- **RA 10173**: Republic Act 10173 (Data Privacy Act of the Philippines), which governs the collection and storage of biometric data. Consent must be obtained before enrollment.
- **ISO/IEC 25010**: The software quality model against which SmartFace is evaluated, covering functional suitability, performance efficiency, compatibility, usability, reliability, and portability.
- **Audit_Log**: A database record capturing user actions (login, enrollment, manual override, user deactivation) with timestamp, IP address, and details.
- **DB**: The MySQL database `smartface_db` accessed via `mysql-connector-python`.

---

## Requirements

### Requirement 1: User Authentication and Session Management

**User Story:** As a registered user of any role, I want to log in with my credentials, so that I can access the features permitted by my role and have my session securely managed.

#### Acceptance Criteria

1. WHEN a user submits valid credentials to the login endpoint, THE Authentication_System SHALL create a server-side session, record a login entry in the Audit_Log containing the user identifier and timestamp, and redirect the user to their role-appropriate landing page within 3 seconds.
2. WHEN a user submits credentials where the email does not exist or the password does not match the stored hash, THE Authentication_System SHALL return the login page with a generic error message indicating that the credentials are invalid and SHALL NOT reveal which field was incorrect.
3. WHEN a user submits credentials that fail validation 5 consecutive times within a 15-minute window, THE Authentication_System SHALL lock the account for 15 minutes and display an error message indicating the account is temporarily locked.
4. WHEN a logged-in user accesses the logout endpoint, THE Authentication_System SHALL invalidate the server-side session, record a logout entry in the Audit_Log containing the user identifier and timestamp, and redirect the user to the login page within 3 seconds.
5. WHILE a user's session has been inactive for more than 30 minutes, THE Authentication_System SHALL invalidate the session and redirect the user to the login page on their next request, with an error message indicating the session has expired.
6. THE Authentication_System SHALL store all passwords as bcrypt hashes using `werkzeug.security` and SHALL NOT store plaintext passwords at any point during registration, login, or password update operations.
7. IF a request is made to any protected route without an active session, THEN THE Authentication_System SHALL redirect the user to the login page without exposing the protected route's response data.

---

### Requirement 2: Role-Based Access Control (RBAC)

**User Story:** As a system owner, I want access to each route to be restricted by user role, so that Students cannot access other users' data, Faculty/Staff cannot perform administrative actions, and sensitive operations remain under Administrator control.

#### Acceptance Criteria

1. THE RBAC_System SHALL enforce role restrictions on every protected route using a `@role_required` decorator applied at the route level.
2. IF a user with the `student` role attempts to access any route other than `/my-attendance` and `/logout`, THEN THE RBAC_System SHALL return a 403 Forbidden response with an error message indicating insufficient permissions, without exposing any data from the requested route.
3. IF a user with the `faculty` role attempts to access any Administrator-only route (user management, enrollment, audit logs, manual override), THEN THE RBAC_System SHALL return a 403 Forbidden response with an error message indicating insufficient permissions, without exposing any data from the requested route.
4. THE RBAC_System SHALL permit Administrators to access all routes without restriction.
5. THE RBAC_System SHALL permit Faculty/Staff to access `/kiosk`, `/dashboard`, `/api/live-feed`, `/api/recognize`, `/reports`, and `/reports/export`, and deny access to all other protected routes with a 403 Forbidden response.
6. THE RBAC_System SHALL permit Students to access only `/my-attendance` and `/logout`, and deny access to all other routes with a 403 Forbidden response.
7. IF a request is made to any protected route without a valid authenticated session, THEN THE RBAC_System SHALL return a 401 Unauthorized response before role evaluation is performed.
8. IF the `@role_required` decorator is applied to a route and the authenticated user's role is not defined in the system's role permission table, THEN THE RBAC_System SHALL deny access with a 403 Forbidden response and log an error indicating an unrecognized role value.

---

### Requirement 3: Face Enrollment

**User Story:** As an Administrator, I want to enroll a new user by capturing 3–5 face samples from a webcam, so that the system can recognize that user during kiosk sessions.

#### Acceptance Criteria

1. WHEN an Administrator accesses the enrollment page, THE Enrollment_UI SHALL display a form containing fields for full name (1–100 characters), email address (valid format, maximum 254 characters), ID number (1–50 characters), department (1–100 characters), and role (one of: Student, Faculty, Staff, Admin), a consent checkbox referencing RA 10173, and a webcam capture area streaming the live camera feed at a minimum resolution of 320×240 pixels.
2. WHEN the Administrator initiates enrollment, THE Enrollment_UI SHALL capture exactly 3 to 5 still frames from the webcam stream and display a thumbnail preview of each captured sample before submission, where each captured frame is a JPEG image no larger than 5 MB.
3. WHEN the enrollment form is submitted without the consent checkbox checked, THE Enrollment_System SHALL reject the submission without creating any database records and SHALL display an error message indicating that consent under RA 10173 is required.
4. WHEN `POST /api/enroll` receives a valid enrollment request with 3–5 face images, a complete user record, and consent given, THE Enrollment_System SHALL create a user row in the `users` table with `consent_given = 1`, compute a facial encoding for each sample image, persist each encoding as a BLOB in the `face_encodings` table linked to the user row, save each raw JPEG to `uploads/face_samples/`, record an enrollment entry in the Audit_Log containing the administrator's identity, the enrolled user's ID, and a UTC timestamp, and call `reload_known_faces()` to refresh the Encoding_Cache, completing the full operation within 30 seconds.
5. IF `POST /api/enroll` receives an image in which no face is detected, THEN THE Enrollment_System SHALL return a descriptive JSON error identifying which sample index (1–5) failed face detection and SHALL NOT create any database records for that submission.
6. IF `POST /api/enroll` receives a user email or ID number that already exists in the `users` table, THEN THE Enrollment_System SHALL return a JSON error indicating which field (email or ID number) conflicts with an existing record and SHALL NOT create any database records for that submission.
7. WHEN a facial encoding is stored, THE Enrollment_System SHALL serialize it using `encoding.tobytes()` and SHALL deserialize it using `np.frombuffer(blob, dtype=np.float64)` to guarantee encoding round-trip fidelity.
8. IF any step in the enrollment pipeline fails after the user row has been created (encoding computation, file save, or Audit_Log write), THEN THE Enrollment_System SHALL roll back all database records created during that submission and SHALL return a JSON error indicating which step failed.
9. IF the webcam feed cannot be accessed when the Administrator loads the enrollment page, THEN THE Enrollment_UI SHALL display an error message indicating that camera access is unavailable and SHALL disable the capture controls until camera access is restored.

---

### Requirement 4: In-Memory Encoding Cache

**User Story:** As a system operator, I want facial encodings to be loaded into memory at startup and refreshed after enrollment, so that face matching does not require a database query on every recognition frame.

#### Acceptance Criteria

1. WHEN the SmartFace application starts, THE Face_Service SHALL load all facial encodings and their corresponding `user_id` values from the DB into the Encoding_Cache (a module-level `known_encodings` list) and into a parallel `known_user_ids` list, completing the load within 5 seconds for up to 10,000 encoding entries.
2. WHEN `reload_known_faces()` is called, THE Face_Service SHALL atomically replace both `known_encodings` and `known_user_ids` with data rebuilt from the current state of the DB, such that any face matching request observes either the fully previous or the fully updated cache with no partial state, and SHALL skip any DB row whose encoding value is null or cannot be deserialized, completing the rebuild within 5 seconds for up to 10,000 encoding entries.
3. WHILE the Encoding_Cache is empty (no enrolled users), THE Face_Service SHALL return a list of zero elements for any face matching request without raising an exception.
4. THE Face_Service SHALL keep one entry per face sample in the flat `known_encodings` list, mapping multiple encodings to the same `user_id`, so that users enrolled with multiple samples benefit from higher matching accuracy.
5. WHEN a new face enrollment is successfully persisted to the DB, THE Face_Service SHALL invoke `reload_known_faces()` before returning the enrollment confirmation response, so that the Encoding_Cache reflects the newly added encoding.
6. IF the DB is unreachable when the SmartFace application attempts the startup encoding load, THEN THE Face_Service SHALL start with an empty Encoding_Cache and log an error message indicating that the startup cache load failed, and SHALL remain operational so that `reload_known_faces()` can be retried subsequently.

---

### Requirement 5: Real-Time Face Recognition Pipeline

**User Story:** As a Faculty/Staff member operating the kiosk, I want the system to continuously analyze the webcam feed and identify registered users in real time, so that attendance can be recorded without manual intervention.

#### Acceptance Criteria

1. WHEN the kiosk page is loaded, THE Kiosk_UI SHALL request webcam access via the browser's media device API and, upon permission being granted, render the live video stream in a video element within 3 seconds of page load.
2. IF the user denies webcam permission or no camera device is available, THEN THE Kiosk_UI SHALL display an error message indicating that camera access is required and SHALL NOT proceed with frame capture.
3. WHILE the kiosk page is active and webcam access is granted, THE Kiosk_UI SHALL capture one JPEG frame every 1000 milliseconds (±50 ms) at quality 0.7 and POST the base64-encoded image to the recognition endpoint; if a prior request is still pending when the next capture interval fires, THE Kiosk_UI SHALL skip that capture cycle and resume on the next interval.
4. WHEN the recognition endpoint receives a base64-encoded JPEG frame, THE Recognition_Service SHALL decode the image, downscale it to 0.25× its original dimensions before computing face locations, convert the color space from BGR to RGB, run face location detection and face encoding extraction, and compare each detected encoding against the Encoding_Cache using face distance comparison, completing the full pipeline within 3000 milliseconds of receiving the request.
5. IF the Recognition_Service cannot decode the submitted base64 string into a valid image, THEN THE Recognition_Service SHALL return HTTP 400 with an error message indicating an invalid image payload and SHALL NOT attempt face detection.
6. WHEN a face's best distance is less than or equal to 0.45, THE Recognition_Service SHALL identify the face as belonging to the matched user, compute confidence as `round((1 - best_distance) * 100, 2)` yielding a value between 0.00 and 100.00, and include `user_id`, `full_name`, `confidence`, and `bounding_box` (expressed as pixel coordinates: top, right, bottom, left relative to the original frame dimensions) in the faces array of the JSON response.
7. WHEN a face's best distance exceeds 0.45, THE Recognition_Service SHALL include that face in the response faces array with `user_id` set to `null`, `full_name` set to `"Unknown"`, and a `bounding_box`, and SHALL NOT trigger attendance logging for that face.
8. IF no face is detected in a submitted frame, THEN THE Recognition_Service SHALL return `{"faces": []}` with HTTP 200 and SHALL NOT raise a server error.
9. WHEN the recognition endpoint returns a successful JSON response, THE Kiosk_UI SHALL clear the overlay canvas and redraw a bounding box and a label showing the name and confidence value for each face entry in the response within 200 milliseconds of receiving the response.
10. WHEN multiple faces are detected in a single frame, THE Recognition_Service SHALL process all detected faces in the frame, return a result entry for each face in the response, and trigger attendance logging independently for each face whose best distance is less than or equal to 0.45.

---

### Requirement 6: Attendance Logging with Debounce

**User Story:** As an Administrator, I want attendance records to be created automatically when a student is recognized, with intelligent debouncing to avoid duplicate entries, so that the attendance log is accurate and not inflated by repeated recognitions.

#### Acceptance Criteria

1. WHEN a registered user is recognized for the first time on a given calendar date, THE Attendance_Service SHALL insert a row into the `attendance` table with `time_in` set to the current server time and `status` set to `'present'` if `time_in` is at or before LATE_TIME, or `'late'` if `time_in` is after LATE_TIME.
2. WHEN a registered user is recognized on a date for which an attendance record already exists and the elapsed time since the value stored in Last_Seen_Dict for that `user_id` is greater than or equal to 60 seconds, THE Attendance_Service SHALL update the existing row's `time_out` to the current server time.
3. WHEN a registered user is recognized and the elapsed time since the value stored in Last_Seen_Dict for that `user_id` is less than 60 seconds, THE Attendance_Service SHALL skip the database operation and return the cached match result without modifying the `attendance` table or Last_Seen_Dict.
4. THE Attendance_Service SHALL use `INSERT INTO attendance ... ON DUPLICATE KEY UPDATE` to enforce the `UNIQUE KEY uniq_user_day (user_id, date)` constraint and prevent duplicate daily rows at the database level.
5. WHEN an attendance record is successfully inserted or updated in the `attendance` table, THE Attendance_Service SHALL update Last_Seen_Dict with the current server timestamp for the recognized `user_id`.
6. THE Attendance_Service SHALL expose TOLERANCE and LATE_TIME as configurable values in `config.py` so they can be adjusted without modifying application code.
7. IF the database operation in criteria 1 or 2 fails, THEN THE Attendance_Service SHALL leave Last_Seen_Dict unchanged and return an error response indicating the attendance record could not be saved, without modifying any previously stored attendance data.
8. WHEN a registered user is recognized for the first time on a given calendar date and no entry exists in Last_Seen_Dict for that `user_id`, THE Attendance_Service SHALL treat the elapsed time as exceeding 60 seconds and proceed with the insert operation defined in criterion 1.

---

### Requirement 7: Dashboard and Live Feed

**User Story:** As an Administrator or Faculty/Staff member, I want to view today's attendance summary and a live-updating table of recognized users, so that I can monitor attendance as it happens.

#### Acceptance Criteria

1. WHEN an Administrator or Faculty/Staff member accesses the dashboard, THE Dashboard_UI SHALL display summary cards showing the count of students marked present today, the count marked late today, and the total number of registered active users, where each count is a non-negative integer.
2. WHILE the dashboard page is open, THE Dashboard_UI SHALL poll the live-feed endpoint at an interval of exactly 3 seconds and update the attendance table in place without a full page reload.
3. WHEN the live-feed endpoint is called, THE Dashboard_Service SHALL return a list of today's attendance records, each containing full_name, id_number, time_in, time_out, status, and confidence, where time_in and time_out are in HH:MM:SS format, status is one of "present", "late", or "absent", and confidence is a percentage value between 0.00 and 100.00.
4. THE Dashboard_Service SHALL return only records whose date matches the current calendar date in the server's configured timezone.
5. IF the live-feed endpoint returns an error or does not respond within 5 seconds, THEN THE Dashboard_UI SHALL retain the last successfully loaded attendance table and display an error indicator informing the user that the live feed is temporarily unavailable.
6. IF an authenticated user whose role is neither Administrator nor Faculty/Staff accesses the dashboard, THEN THE Dashboard_UI SHALL deny access and display a message indicating insufficient permissions.

---

### Requirement 8: Attendance Reports and CSV Export

**User Story:** As an Administrator or Faculty/Staff member, I want to filter attendance records by date range, role, and department and export the results as a CSV file, so that I can generate reports for institutional use.

#### Acceptance Criteria

1. WHEN an Administrator or Faculty/Staff member accesses the reports page, THE Reports_UI SHALL display filter controls for start date, end date, role, and department, WHERE start date and end date accept values in YYYY-MM-DD format, role accepts one of the defined system roles, and department accepts a department name of up to 100 characters.
2. WHEN an Administrator or Faculty/Staff member submits the filter form with valid inputs, THE Reports_UI SHALL render a paginated table of matching attendance records displaying at most 50 records per page, with each page loaded within 3 seconds.
3. IF the submitted filter form contains a start date later than the end date, THEN THE Reports_UI SHALL display an error message indicating the invalid date range and SHALL NOT submit the request.
4. WHEN a CSV export is requested with valid filter parameters, THE Reports_Service SHALL return a downloadable CSV file containing all matching attendance records with the columns `full_name`, `id_number`, `department`, `role`, `date`, `time_in`, `time_out`, `status`, and `confidence`, in that column order, with a header row as the first line.
5. IF no records match the applied filters, THEN THE Reports_Service SHALL return a downloadable CSV file containing only the header row and SHALL NOT return an error response.
6. IF the CSV export request contains a start date later than the end date or a role or department value not recognized by the system, THEN THE Reports_Service SHALL return an error response indicating the invalid filter parameter and SHALL NOT return a CSV file.

---

### Requirement 9: Manual Attendance Override

**User Story:** As an Administrator, I want to manually mark a student as present on a given date, so that I can correct attendance records when the automatic system fails or a student has a legitimate exemption.

#### Acceptance Criteria

1. WHEN an Administrator submits a manual attendance override request with a valid `user_id` and `date`, THE Override_Service SHALL insert a new attendance record if none exists for that `user_id` and `date`, or update the existing record, setting `status` to `'manual'` and `marked_by` to the Administrator's `user_id`.
2. WHEN a manual attendance override request is submitted, THE Override_Service SHALL write an audit log entry recording the Administrator's `user_id`, the target `user_id`, the overridden date, and the IP address of the request within 2 seconds of the override being applied.
3. IF a manual attendance override request is submitted with a `user_id` that does not exist in the `users` table, THEN THE Override_Service SHALL return an error message indicating the user was not found and SHALL NOT insert or update any attendance record.
4. IF a manual attendance override request is submitted with a `date` value that is not a valid calendar date or is more than 365 days in the past, THEN THE Override_Service SHALL return an error message indicating the date is invalid and SHALL NOT insert or update any attendance record.
5. IF the audit log write fails after a manual attendance override is successfully applied, THEN THE Override_Service SHALL roll back the attendance record change and return an error message indicating the operation could not be completed.

---

### Requirement 10: User Management

**User Story:** As an Administrator, I want to view, edit, and deactivate registered users, so that I can manage the user base and revoke access when needed.

#### Acceptance Criteria

1. WHEN an Administrator accesses the user management page, THE User_Management_UI SHALL display a paginated list of all users showing `full_name`, `id_number`, `role`, `department`, and `is_active` status, with at most 25 users per page.
2. WHEN an Administrator edits a user's profile fields (full name, department, role, id_number), THE User_Management_Service SHALL update the corresponding fields in the `users` table and return a success confirmation.
3. WHEN an Administrator deactivates a user, THE User_Management_Service SHALL set `is_active = 0` for that user, write a deactivation entry to `audit_logs`, invalidate any active session belonging to that user, and prevent that user from logging in.
4. WHEN an Administrator requests deletion of a user's biometric data, THE User_Management_Service SHALL delete all rows in `face_encodings` for that `user_id`, delete all raw JPEG files in `uploads/face_samples/` associated with that user, and call `reload_known_faces()` so that subsequent recognition attempts no longer match the deleted user.
5. IF an Administrator attempts to deactivate their own account, THEN THE User_Management_Service SHALL reject the request and return an error message stating "You cannot deactivate your own account."

---

### Requirement 11: Audit Log Viewer

**User Story:** As an Administrator, I want to view a log of all significant system actions, so that I can track who did what and when for accountability and RA 10173 compliance.

#### Acceptance Criteria

1. WHEN an Administrator accesses the audit log page, THE Audit_UI SHALL display a paginated, reverse-chronological list of audit log entries showing timestamp, acting user identifier, action type, details, and IP address, with at most 25 entries per page and filter controls for action type and date range.
2. THE Audit_Service SHALL write an audit log entry for each of the following actions: user login, user logout, user enrollment, manual attendance override, user deactivation, and biometric data deletion.
3. IF a write to the `audit_logs` table fails, THEN THE Audit_Service SHALL log the failure to the application error log and SHALL NOT silently discard the record or allow the failure to propagate as an unhandled exception to the end user.

---

### Requirement 12: Student Self-Service Attendance View

**User Story:** As a Student, I want to view my own attendance history, so that I can monitor my participation records without accessing any other user's data.

#### Acceptance Criteria

1. WHEN a Student accesses the self-service attendance page, THE Self_Service_UI SHALL display only the attendance records associated with the currently logged-in Student's `user_id`.
2. THE Self_Service_UI SHALL display records sorted by date in descending order (most recent first), showing `date`, `time_in`, `time_out`, and `status` for each entry, where `status` is one of "Present", "Late", or "Absent".
3. IF no attendance records exist for the logged-in Student, THEN THE Self_Service_UI SHALL display the message "No attendance records found." and SHALL NOT display records belonging to any other user.

---

### Requirement 13: Camera Error Handling and User Guidance

**User Story:** As a kiosk operator, I want the system to gracefully handle camera failures and poor image conditions, so that the kiosk remains usable and communicates actionable feedback.

#### Acceptance Criteria

1. IF `navigator.mediaDevices.getUserMedia()` is denied or unavailable, THEN THE Kiosk_UI SHALL display an instruction panel explaining how to grant camera permissions and SHALL NOT display a blank or broken screen.
2. WHEN the Kiosk_UI captures a frame, THE Kiosk_UI SHALL compute the mean pixel brightness of the frame on a 0–255 scale and SHALL display a visible warning banner when the mean brightness falls below 50, and SHALL remove the warning when a subsequent frame's mean brightness is 50 or above.
3. WHEN the Recognition_Service returns `{"faces": []}`, THE Kiosk_UI SHALL display a "No face detected" status indicator and SHALL continue the capture loop without stopping.
4. WHEN the Recognition_Service returns a result containing one or more `"Unknown"` faces, THE Kiosk_UI SHALL display an "Unknown" label with a bounding box for each unrecognized face and SHALL NOT log any attendance record for those faces.

---

### Requirement 14: Liveness and Anti-Spoofing (Stated Limitation)

**User Story:** As a system evaluator, I want the system to document its approach to photo spoofing, so that the panel understands the security posture and planned mitigation path.

#### Acceptance Criteria

1. THE SmartFace application code SHALL contain a comment block in the recognition pipeline that identifies the exact line after which a liveness check would be inserted, such that the hook location is locatable by reading the source file without executing the application.
2. THE SmartFace system documentation SHALL explicitly state that photo spoofing is a known limitation of the current implementation and that liveness detection is deferred as a future enhancement.

---

### Requirement 15: Performance and Compatibility

**User Story:** As a thesis evaluator applying ISO/IEC 25010, I want SmartFace to meet defined performance and compatibility targets, so that it can be scored favorably on performance efficiency and compatibility quality characteristics.

#### Acceptance Criteria

1. WHEN a user navigates to any page in SmartFace, THE SmartFace application SHALL render and deliver the complete page response within 3 seconds under a single concurrent user on a network connection of at least 10 Mbps.
2. WHEN `POST /api/recognize` receives a single frame, THE Recognition_Service SHALL return a JSON response within 2 seconds on hardware meeting or exceeding a quad-core CPU and 8 GB RAM with no concurrent GPU-intensive processes running.
3. THE SmartFace application SHALL function correctly in the latest stable release of Google Chrome, Microsoft Edge, and Mozilla Firefox on Windows 10 or later without requiring browser-specific workarounds.
4. WHERE the SmartFace application is accessed over a LAN with a server reachable on the network and `getUserMedia` served over HTTPS or localhost, THE SmartFace application SHALL meet the same page response time and recognition response time targets defined in criteria 1 and 2.
