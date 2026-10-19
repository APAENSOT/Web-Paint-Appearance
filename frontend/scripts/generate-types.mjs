import { writeFile } from "node:fs/promises";
import openapiTS, { astToString, COMMENT_HEADER } from "openapi-typescript";
import ts from "typescript";

const ast = await openapiTS(new URL("../../docs/openapi.json", import.meta.url), {
  transform(schema) {
    if (schema.contentMediaType === "application/octet-stream") {
      return ts.factory.createTypeReferenceNode("Blob");
    }
  },
});
await writeFile(new URL("../src/api/types.ts", import.meta.url), COMMENT_HEADER + astToString(ast));
