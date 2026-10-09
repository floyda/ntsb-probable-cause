# 0166 — The live shadow reads the store with a dedicated, read-only AWS key

From Andy, 2026-10-08, during S3.3's first mornings. Amends nothing else. Detail: the S3.3 plan's
Deviations (Task 11) and the runbook section "The live shadow's AWS key".

## Context

1. **The morning needs two AWS permissions.** It reads the object `recorder.sqlite` in the
   recorder's store bucket (`s3:GetObject`). It reads the outputs of the `NtsbRecorderStack` stack
   (`cloudformation:DescribeStacks`), so `scripts/live_env.sh` can find the bucket name. Nothing
   else.
2. **Until now it used the `ntsb` profile.** That profile is an assume-role profile on Andy's own
   `default` user. It takes `OrganizationAccountAccessRole`, an administrator role, in the project
   account. It works only after `aws login`.
3. **The `aws login` session expired within the day.** The second morning of 2026-10-08 was
   refused by an expired session about nineteen hours after a login. Nothing was spent. A morning
   that needs a fresh login most days needs Andy present.

## Decision

1. **A dedicated IAM user, `ntsb-live-reader`, in the project account**, created by hand, outside
   the CDK stack. Its inline policy `live-shadow-read-store` grants only the two actions above:
   `s3:GetObject` on `arn:aws:s3:::<the store bucket>/recorder.sqlite`, and
   `cloudformation:DescribeStacks` on the `NtsbRecorderStack` stack.
2. **Its access key is kept in `pass`** as `aws/ntsb-live-reader`, and read through the AWS CLI
   profile `ntsb-live` (`region = eu-west-2`, `credential_process = pass show aws/ntsb-live-reader`).
3. **`scripts/live_env.sh` defaults to `ntsb-live`.** An explicitly set `AWS_PROFILE` or
   `NTSB_STORE` still wins. Mornings need no `aws login`, only `pass` unlocked.
4. **S4 replaces this** with the cloud task's own role. The runbook lists the removal commands.
5. **The user, policy and key were created by Andy's own commands.** The permission system kept
   those commands for him. The policy text, as written, is:

   ```
   {
     "Version": "2012-10-17",
     "Statement": [
       {"Effect": "Allow", "Action": "s3:GetObject",
        "Resource": "arn:aws:s3:::<the store bucket>/recorder.sqlite"},
       {"Effect": "Allow", "Action": "cloudformation:DescribeStacks",
        "Resource": "arn:aws:cloudformation:eu-west-2:<account>:stack/NtsbRecorderStack/*"}
     ]
   }
   ```

   (The bucket name and account number are left out of this record. The exact text is in AWS.)

## Why

1. **A smaller risk.** A key that can only read public NTSB case data is a smaller risk than a
   daily login to an administrator role.
2. **Mornings no longer need Andy present.** There is no login to refresh. A morning can start
   whenever `pass` is unlocked.

## What this rules out

- **A permanent key for Andy's own user.** That would be, in effect, a permanent administrator key
  across both accounts.
- **Keeping daily logins.** The session ended within the day, so a morning could be refused for a
  reason unrelated to the work.
- **Adding the user to the CDK stack now.** S4 replaces the user with the cloud task's role, so
  codifying it would add work that is deleted soon.

## Status

Accepted, 2026-10-08 (Andy: "yes make the change").

## Glossary

- **IAM user**: a sign-in identity inside an AWS account, with its own permissions.
- **Access key**: a pair of secret strings that lets a program sign in as an IAM user without a
  password. It does not end after a few hours.
- **`credential_process`**: a line in an AWS profile that names a command to run to get the key.
  Here the command is `pass show aws/ntsb-live-reader`.
- **Inline policy**: a list of allowed actions stored on one IAM user.
- **CDK stack**: the code that sets up the recorder's AWS parts. The user is not part of it.
