"use client";

import { useState } from "react";
import { Check, ChevronsUpDown, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";
import {
  COCO_CLASSES,
  parseClasses,
  serializeClasses,
} from "@/lib/constants/coco-classes";

interface RfDetrClassPickerProps {
  /** Comma-separated list of selected class names (the query string). */
  value: string;
  onChange: (value: string) => void;
  /** Text shown on the trigger when nothing is selected. */
  placeholder: string;
  searchPlaceholder: string;
  emptyText: string;
  /** "N classes selected" — `{count}` is replaced with the number selected. */
  selectedLabel: string;
}

/**
 * Multi-select picker for RF-DETR's closed COCO vocabulary. RF-DETR can detect
 * several classes at once, so this lets the user pick one or more classes
 * instead of guessing the free-text syntax. Leaving the selection empty means
 * "detect everything", matching the backend's behaviour for an empty query.
 */
export function RfDetrClassPicker({
  value,
  onChange,
  placeholder,
  searchPlaceholder,
  emptyText,
  selectedLabel,
}: RfDetrClassPickerProps) {
  const [open, setOpen] = useState(false);
  const selected = parseClasses(value);

  const toggle = (cls: string) => {
    const next = selected.includes(cls)
      ? selected.filter((c) => c !== cls)
      : [...selected, cls];
    onChange(serializeClasses(next));
  };

  const remove = (cls: string) => {
    onChange(serializeClasses(selected.filter((c) => c !== cls)));
  };

  return (
    <div className="space-y-2">
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button
            type="button"
            variant="outline"
            role="combobox"
            aria-expanded={open}
            className="w-full justify-between font-normal"
          >
            <span className={cn(selected.length === 0 && "text-muted-foreground")}>
              {selected.length === 0
                ? placeholder
                : selectedLabel.replace("{count}", String(selected.length))}
            </span>
            <ChevronsUpDown className="h-4 w-4 shrink-0 opacity-50" />
          </Button>
        </PopoverTrigger>
        <PopoverContent
          className="w-[var(--radix-popover-trigger-width)] p-0"
          align="start"
        >
          <Command>
            <CommandInput placeholder={searchPlaceholder} />
            <CommandList>
              <CommandEmpty>{emptyText}</CommandEmpty>
              <CommandGroup>
                {COCO_CLASSES.map((cls) => {
                  const isSelected = selected.includes(cls);
                  return (
                    <CommandItem
                      key={cls}
                      value={cls}
                      onSelect={() => toggle(cls)}
                    >
                      <Check
                        className={cn(
                          "mr-2 h-4 w-4",
                          isSelected ? "opacity-100" : "opacity-0",
                        )}
                      />
                      <span className="capitalize">{cls}</span>
                    </CommandItem>
                  );
                })}
              </CommandGroup>
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>

      {selected.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {selected.map((cls) => (
            <Badge key={cls} variant="secondary" className="gap-1 capitalize">
              {cls}
              <button
                type="button"
                onClick={() => remove(cls)}
                className="ml-0.5 rounded-full outline-none hover:text-destructive focus-visible:ring-2 focus-visible:ring-ring"
                aria-label={`Remove ${cls}`}
              >
                <X className="h-3 w-3" />
              </button>
            </Badge>
          ))}
        </div>
      )}
    </div>
  );
}
