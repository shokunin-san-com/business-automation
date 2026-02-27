"use client";

// Re-export the edit page with "new" as ID
// The [id]/page.tsx handles isNew = id === "new"
import PostEditPage from "../[id]/page";
export default PostEditPage;
