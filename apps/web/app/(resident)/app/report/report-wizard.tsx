"use client";

import Image from "next/image";
import Link from "next/link";
import { type ChangeEvent, useEffect, useId, useRef, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { PageFrame } from "@/components/page-frame";

type CategoryId =
  | "plumbing"
  | "heating-cooling"
  | "electrical"
  | "appliance"
  | "water-leak"
  | "other";
type AccessPermission = "yes" | "no" | "contact-me";
type PreferredWindow = "morning" | "afternoon" | "evening" | "contact-me";
type Step = 1 | 2 | 3;

type Category = {
  id: CategoryId;
  label: string;
  description: string;
};

type PhotoDraft = {
  id: string;
  name: string;
  previewUrl: string;
};

const categories: readonly Category[] = [
  {
    id: "plumbing",
    label: "Plumbing",
    description: "Sink, toilet, drain, pipe, or water pressure",
  },
  {
    id: "heating-cooling",
    label: "Heating & cooling",
    description: "Heat, air conditioning, thermostat, or ventilation",
  },
  {
    id: "electrical",
    label: "Electrical",
    description: "Outlet, light, breaker, smoke, or sparks",
  },
  {
    id: "appliance",
    label: "Appliance",
    description: "Refrigerator, dishwasher, oven, laundry, or disposal",
  },
  {
    id: "water-leak",
    label: "Water leak",
    description: "Active leak, ceiling water, flooding, or sewage",
  },
  {
    id: "other",
    label: "Something else",
    description: "Door, window, pest, noise, or another concern",
  },
] as const;

const accessOptions: readonly {
  id: AccessPermission;
  label: string;
  description: string;
}[] = [
  {
    id: "yes",
    label: "Yes, maintenance may enter",
    description: "You do not need to be home during the agreed window.",
  },
  {
    id: "no",
    label: "No, I need to be present",
    description: "We will use your preferred window to coordinate a visit.",
  },
  {
    id: "contact-me",
    label: "Contact me first",
    description: "A team member should confirm access before scheduling.",
  },
] as const;

const accessWindows: readonly {
  id: PreferredWindow;
  label: string;
  description: string;
}[] = [
  { id: "morning", label: "Morning", description: "8:00 AM–12:00 PM" },
  { id: "afternoon", label: "Afternoon", description: "12:00 PM–4:00 PM" },
  { id: "evening", label: "Evening", description: "4:00 PM–7:00 PM" },
  { id: "contact-me", label: "Contact me", description: "Choose a time together" },
] as const;

const totalSteps = 3;
const maximumPhotos = 5;
const maximumPhotoBytes = 10 * 1024 * 1024;
const acceptedPhotoTypes = new Set([
  "image/heic",
  "image/jpeg",
  "image/png",
  "image/webp",
]);

export function ReportWizard() {
  const descriptionId = useId();
  const photoInputId = useId();
  const [step, setStep] = useState<Step>(1);
  const [category, setCategory] = useState<CategoryId | null>(null);
  const [description, setDescription] = useState("");
  const [photos, setPhotos] = useState<readonly PhotoDraft[]>([]);
  const [photoError, setPhotoError] = useState<string | null>(null);
  const [accessPermission, setAccessPermission] = useState<AccessPermission | null>(null);
  const [preferredWindow, setPreferredWindow] = useState<PreferredWindow | null>(null);
  const latestPhotos = useRef<readonly PhotoDraft[]>(photos);

  useEffect(() => {
    latestPhotos.current = photos;
  }, [photos]);

  useEffect(() => {
    return () => {
      latestPhotos.current.forEach((photo) => URL.revokeObjectURL(photo.previewUrl));
    };
  }, []);

  const selectedCategory = categories.find((item) => item.id === category);
  const canContinue =
    (step === 1 && category !== null && description.trim().length > 0) ||
    step === 2 ||
    (step === 3 && accessPermission !== null && preferredWindow !== null);

  function addPhotos(event: ChangeEvent<HTMLInputElement>) {
    const selectedFiles = Array.from(event.target.files ?? []);
    const acceptedFiles = selectedFiles.filter(
      (file) =>
        acceptedPhotoTypes.has(file.type) &&
        file.size > 0 &&
        file.size <= maximumPhotoBytes,
    );
    const remainingSlots = maximumPhotos - photos.length;
    if (selectedFiles.some((file) => !acceptedPhotoTypes.has(file.type))) {
      setPhotoError(
        "Only JPEG, PNG, WebP, and HEIC image files can be added to this report.",
      );
    } else if (selectedFiles.some((file) => file.size === 0 || file.size > maximumPhotoBytes)) {
      setPhotoError("Each photo must be larger than 0 bytes and no more than 10 MB.");
    } else if (acceptedFiles.length > remainingSlots) {
      setPhotoError(`Add up to ${maximumPhotos} photos. Remove a photo before adding another.`);
    } else {
      setPhotoError(null);
    }
    const acceptedPhotos = acceptedFiles
      .slice(0, Math.max(remainingSlots, 0))
      .map((file) => ({
        id: `${file.name}-${file.lastModified}-${crypto.randomUUID()}`,
        name: file.name,
        previewUrl: URL.createObjectURL(file),
      }));
    setPhotos((currentPhotos) => [...currentPhotos, ...acceptedPhotos]);
    event.target.value = "";
  }

  function removePhoto(index: number) {
    const removedPhoto = photos[index];
    if (removedPhoto) {
      URL.revokeObjectURL(removedPhoto.previewUrl);
    }
    setPhotos((currentPhotos) =>
      currentPhotos.filter((_, photoIndex) => photoIndex !== index),
    );
    setPhotoError(null);
  }

  function continueToNextStep() {
    if (canContinue && step < totalSteps) {
      setStep((currentStep) => (currentStep + 1) as Step);
    }
  }

  return (
    <PageFrame
      description="Tell us what is happening, add photos if they help, and share access preferences. This safe UI-only boundary keeps your draft in the browser until ticket creation has an approved API contract."
      eyebrow="Resident report"
      title="Report a maintenance issue"
    >
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <Card>
          <CardHeader className="gap-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <Badge variant="outline">Step {step} of {totalSteps}</Badge>
              <p className="text-xs font-medium text-muted-foreground">
                No model call occurs in this flow.
              </p>
            </div>
            <CardTitle>{stepTitle(step)}</CardTitle>
            <CardDescription>{stepDescription(step)}</CardDescription>
          </CardHeader>
          <CardContent>
            {step === 1 ? (
              <IssueStep
                category={category}
                description={description}
                descriptionId={descriptionId}
                onCategoryChange={setCategory}
                onDescriptionChange={setDescription}
              />
            ) : null}
            {step === 2 ? (
              <PhotosStep
                inputId={photoInputId}
                onPhotoChange={addPhotos}
                onRemovePhoto={removePhoto}
                photoError={photoError}
                photos={photos}
              />
            ) : null}
            {step === 3 ? (
              <AccessStep
                accessPermission={accessPermission}
                onAccessChange={setAccessPermission}
                onWindowChange={setPreferredWindow}
                preferredWindow={preferredWindow}
              />
            ) : null}
          </CardContent>
          <CardFooter className="flex flex-wrap justify-between gap-3">
            {step > 1 ? (
              <Button
                onClick={() => setStep((currentStep) => (currentStep - 1) as Step)}
                variant="outline"
              >
                Back
              </Button>
            ) : (
              <Button render={<Link href="/app" />} variant="outline">
                Cancel
              </Button>
            )}
            {step < totalSteps ? (
              <Button disabled={!canContinue} onClick={continueToNextStep}>
                Continue
              </Button>
            ) : (
              <Button aria-describedby="submission-boundary" disabled>
                Submit report
              </Button>
            )}
          </CardFooter>
        </Card>

        <aside className="grid content-start gap-5" aria-label="Report progress and submission status">
          <ProgressCard step={step} />
          {step === 3 ? (
            <ReviewCard
              accessPermission={accessPermission}
              category={selectedCategory?.label ?? "Not selected"}
              description={description}
              photoCount={photos.length}
              preferredWindow={preferredWindow}
            />
          ) : null}
          <Card className="border-primary/30 bg-primary/5" size="sm">
            <CardHeader>
              <CardTitle>Submission boundary</CardTitle>
            </CardHeader>
            <CardContent className="text-sm leading-6 text-muted-foreground">
              <p id="submission-boundary">
                The public API currently exposes ticket reads only. This page does
                not claim a ticket number, upload a photo, or queue a hidden model
                task.
              </p>
              <p className="mt-3">
                When the POST contract is accepted, it must persist and enqueue
                first, then return an acknowledgement in under one second before
                any model work begins.
              </p>
            </CardContent>
          </Card>
        </aside>
      </div>
    </PageFrame>
  );
}

function IssueStep({
  category,
  description,
  descriptionId,
  onCategoryChange,
  onDescriptionChange,
}: {
  category: CategoryId | null;
  description: string;
  descriptionId: string;
  onCategoryChange: (category: CategoryId) => void;
  onDescriptionChange: (description: string) => void;
}) {
  return (
    <div className="grid gap-7">
      <fieldset>
        <legend className="text-sm font-medium">What needs attention?</legend>
        <p className="mt-1 text-sm text-muted-foreground">
          Choose the closest category. You can explain in your own words below.
        </p>
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          {categories.map((item) => {
            return (
              <label
                className="flex min-h-28 cursor-pointer flex-col rounded-xl border bg-card p-4 text-left transition-colors hover:border-primary/60 hover:bg-primary/5 focus-within:ring-3 focus-within:ring-ring/50 focus-within:outline-none has-[:checked]:border-primary has-[:checked]:bg-primary/10"
                key={item.id}
              >
                <input
                  checked={item.id === category}
                  className="sr-only"
                  name="issue-category"
                  onChange={() => onCategoryChange(item.id)}
                  type="radio"
                  value={item.id}
                />
                <span className="block text-base font-medium">{item.label}</span>
                <span className="mt-2 block text-sm leading-5 text-muted-foreground">{item.description}</span>
              </label>
            );
          })}
        </div>
      </fieldset>
      <div className="grid gap-2">
        <Label htmlFor={descriptionId}>What is happening?</Label>
        <textarea
          aria-describedby={`${descriptionId}-hint`}
          className="min-h-32 w-full resize-y rounded-lg border border-input bg-transparent px-3 py-2 text-base outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 md:text-sm"
          id={descriptionId}
          maxLength={2_000}
          onChange={(event) => onDescriptionChange(event.target.value)}
          placeholder="For example: The kitchen sink fills with water when I run the dishwasher."
          value={description}
        />
        <p className="text-xs leading-5 text-muted-foreground" id={`${descriptionId}-hint`}>
          Include what you see, hear, smell, or when the problem started. Do not include bank, health, or other sensitive information.
        </p>
      </div>
    </div>
  );
}

function PhotosStep({
  inputId,
  onPhotoChange,
  onRemovePhoto,
  photoError,
  photos,
}: {
  inputId: string;
  onPhotoChange: (event: ChangeEvent<HTMLInputElement>) => void;
  onRemovePhoto: (index: number) => void;
  photoError: string | null;
  photos: readonly PhotoDraft[];
}) {
  return (
    <div className="grid gap-6">
      <div className="rounded-xl border border-dashed border-primary/50 bg-primary/5 p-5">
        <p className="text-base font-medium">Start with a photo when it helps explain the issue.</p>
        <p className="mt-2 max-w-xl text-sm leading-6 text-muted-foreground">
          Use your camera for a leak, damaged part, error display, or the area around the issue. You can add up to five images.
        </p>
        <div className="mt-5 flex flex-wrap gap-3">
          <Label
            className="inline-flex h-9 cursor-pointer items-center justify-center rounded-lg bg-primary px-2.5 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/80 focus-within:ring-3 focus-within:ring-ring/50"
            htmlFor={inputId}
          >
            Take or add a photo
          </Label>
          <span className="self-center text-sm text-muted-foreground">{photos.length} of {maximumPhotos} selected</span>
        </div>
        <input
          accept="image/*"
          capture="environment"
          className="sr-only"
          id={inputId}
          multiple
          onChange={onPhotoChange}
          type="file"
        />
      </div>
      <div aria-live="polite">
        <h2 className="text-sm font-medium">Selected photos</h2>
        {photos.length ? (
          <ul className="mt-3 grid gap-2" aria-label="Selected photos">
            {photos.map((photo, index) => (
              <li
                className="grid grid-cols-[5rem_minmax(0,1fr)_auto] items-center gap-3 rounded-lg border p-2"
                key={photo.id}
              >
                <div className="relative h-16 overflow-hidden rounded-md bg-muted">
                  <Image
                    alt={`Selected photo: ${photo.name}`}
                    className="object-cover"
                    fill
                    sizes="80px"
                    src={photo.previewUrl}
                    unoptimized
                  />
                </div>
                <span className="min-w-0 truncate text-sm">{photo.name}</span>
                <Button
                  aria-label={`Remove ${photo.name}`}
                  onClick={() => onRemovePhoto(index)}
                  size="sm"
                  type="button"
                  variant="ghost"
                >
                  Remove
                </Button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-2 text-sm leading-6 text-muted-foreground">No photos selected. You can continue without a photo.</p>
        )}
        {photoError ? <p className="mt-3 text-sm text-destructive" role="alert">{photoError}</p> : null}
      </div>
      <p className="text-xs leading-5 text-muted-foreground">
        Images stay in this browser while the ticket upload API is not available. They are not uploaded or sent to a model from this page.
      </p>
    </div>
  );
}

function AccessStep({
  accessPermission,
  onAccessChange,
  onWindowChange,
  preferredWindow,
}: {
  accessPermission: AccessPermission | null;
  onAccessChange: (permission: AccessPermission) => void;
  onWindowChange: (window: PreferredWindow) => void;
  preferredWindow: PreferredWindow | null;
}) {
  return (
    <div className="grid gap-7">
      <ChoiceFieldset
        legend="May maintenance enter if you are away?"
        name="access-permission"
        onChange={onAccessChange}
        options={accessOptions}
        value={accessPermission}
      />
      <ChoiceFieldset
        legend="What time usually works best?"
        name="preferred-window"
        onChange={onWindowChange}
        options={accessWindows}
        value={preferredWindow}
      />
      <p className="rounded-lg border bg-muted/40 p-4 text-sm leading-6 text-muted-foreground">
        Access instructions are sensitive. Share only what a maintenance team needs to schedule safely; never include alarm codes, passwords, or financial information.
      </p>
    </div>
  );
}

function ChoiceFieldset<T extends string>({
  legend,
  name,
  onChange,
  options,
  value,
}: {
  legend: string;
  name: string;
  onChange: (value: T) => void;
  options: readonly { id: T; label: string; description: string }[];
  value: T | null;
}) {
  return (
    <fieldset>
      <legend className="text-sm font-medium">{legend}</legend>
      <div className="mt-3 grid gap-3">
        {options.map((option) => (
          <label
            className="flex cursor-pointer items-start gap-3 rounded-xl border p-4 transition-colors hover:border-primary/60 has-[:checked]:border-primary has-[:checked]:bg-primary/5"
            key={option.id}
          >
            <input
              checked={value === option.id}
              className="mt-1 size-4 accent-primary"
              name={name}
              onChange={() => onChange(option.id)}
              type="radio"
              value={option.id}
            />
            <span>
              <span className="block text-sm font-medium">{option.label}</span>
              <span className="mt-1 block text-sm leading-5 text-muted-foreground">{option.description}</span>
            </span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

function ProgressCard({ step }: { step: Step }) {
  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle>Report progress</CardTitle>
      </CardHeader>
      <CardContent>
        <ol className="grid gap-3 text-sm">
          {[
            "Describe the issue",
            "Add photos",
            "Share access preferences",
          ].map((label, index) => {
            const stepNumber = index + 1;
            const complete = step > stepNumber;
            const current = step === stepNumber;
            return (
              <li className="flex items-center gap-3" key={label}>
                <span
                  aria-hidden="true"
                  className="grid size-6 place-items-center rounded-full border text-xs font-medium data-[complete=true]:border-primary data-[complete=true]:bg-primary data-[complete=true]:text-primary-foreground data-[current=true]:border-primary data-[current=true]:text-primary"
                  data-complete={complete}
                  data-current={current}
                >
                  {complete ? "✓" : stepNumber}
                </span>
                <span className={current ? "font-medium text-foreground" : "text-muted-foreground"}>{label}</span>
              </li>
            );
          })}
        </ol>
      </CardContent>
    </Card>
  );
}

function ReviewCard({
  accessPermission,
  category,
  description,
  photoCount,
  preferredWindow,
}: {
  accessPermission: AccessPermission | null;
  category: string;
  description: string;
  photoCount: number;
  preferredWindow: PreferredWindow | null;
}) {
  const accessLabel = accessOptions.find((option) => option.id === accessPermission)?.label ?? "Not selected";
  const windowLabel = accessWindows.find((option) => option.id === preferredWindow)?.label ?? "Not selected";
  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle>Review your report</CardTitle>
      </CardHeader>
      <CardContent>
        <dl className="grid gap-3 text-sm">
          <ReviewItem label="Category" value={category} />
          <ReviewItem label="Description" value={description || "Not provided"} />
          <ReviewItem label="Photos" value={`${photoCount} selected`} />
          <ReviewItem label="Access" value={accessLabel} />
          <ReviewItem label="Preferred time" value={windowLabel} />
        </dl>
      </CardContent>
    </Card>
  );
}

function ReviewItem({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs font-medium tracking-wide text-muted-foreground uppercase">{label}</dt>
      <dd className="mt-1 break-words leading-5">{value}</dd>
    </div>
  );
}

function stepTitle(step: Step): string {
  return ["", "Describe the issue", "Add photos", "Access and timing"][step];
}

function stepDescription(step: Step): string {
  return [
    "",
    "Start with the maintenance category that fits best, then describe the problem in your own words.",
    "Photos are optional, but they can help a maintenance team understand what to bring.",
    "Choose how a technician may access the unit and the time that generally works for you.",
  ][step];
}
