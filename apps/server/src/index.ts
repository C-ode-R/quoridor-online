import { buildServer } from "./server.js";

const port = Number(process.env.PORT ?? 3000);
const app = await buildServer();

try {
  await app.listen({ port, host: "0.0.0.0" });
} catch (error) {
  app.log.error(error);
  process.exit(1);
}
